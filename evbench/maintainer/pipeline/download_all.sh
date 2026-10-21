#!/usr/bin/env bash
#
# Batch-download the source reports and time series for every scenario.
#
#   evbench/maintainer/pipeline/download_all.sh                     # all 60, one at a time
#   evbench/maintainer/pipeline/download_all.sh -t hard             # one tier
#   evbench/maintainer/pipeline/download_all.sh -s cboe_vix_volatility_regime_state
#   evbench/maintainer/pipeline/download_all.sh --only timeseries   # skip the ground-truth step
#   evbench/maintainer/pipeline/download_all.sh -j 4                # four scenarios in parallel
#   evbench/maintainer/pipeline/download_all.sh --dry-run           # print the commands, run nothing
#
# This hits live publisher servers and pulls roughly 2.4 GB. It runs one
# scenario at a time by default: the sources are government and
# intergovernmental sites, and hammering them in parallel earns rate limits.
# Raise -j only if you know the publishers tolerate it.
#
# Each scenario logs to logs/download/<id>.log and drops a .done stamp on
# success, so re-running resumes where it stopped. --redo ignores the stamps.
#
set -uo pipefail

TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_ROOT="$(dirname "$TOOLS_DIR")"
REPO_ROOT="$(cd "$CODE_ROOT/../.." && pwd)"
LOG_DIR="$REPO_ROOT/logs/download"
PY="${TIMESAGE_PYTHON:-$REPO_ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
# Where the scenario scripts write. Exported because the scripts' own default
# is the released scenarios/ tree, and an unset variable used to land fresh
# downloads there. Same default as format_all.sh.
export TIMESAGE_DATA_ROOT="${TIMESAGE_DATA_ROOT:-$REPO_ROOT/scenarios_hf}"

JOBS=1
TIMEOUT=1800
RETRIES=2
ONLY=""
EXTRA=""
UNTIL=""
DRY_RUN=0
REDO=0
INSTALL_DEPS=0
KEEP_GOING=0
declare -a WANT_SCENARIOS=()
TIER=""
DOMAIN=""

# Scenarios whose downloads need a free API key. Without it they are skipped
# rather than failed — the run is otherwise complete.
declare -A NEEDS_KEY=(
  [usda_crop_progress_weekly_brief]=NASS_API_KEY
  [eia_wpsr_weekly_petroleum_brief]=EIA_API_KEY
)

REQUIREMENTS="beautifulsoup4 lxml pdfplumber pypdf PyYAML requests xlrd"

die() { printf '%s\n' "$*" >&2; exit 1; }
log() { printf '%s\n' "$*" >&2; }

usage() {
  sed -n '2,/^set -uo/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//; $d'
  cat >&2 <<'EOF'
Options:
  -s, --scenario ID   only this scenario (repeatable)
  -t, --tier TIER     easy | middle | hard
  -d, --domain DOMAIN agriculture | climate | energy | finance | healthcare | transportation
  -j, --jobs N        scenarios in parallel (default 1)
  -o, --only STEP     timeseries | gt
      --extra "FLAGS" extra flags, applied only to steps that declare them
      --until DATE    extend each scenario's end bound to this date
      --timeout SEC   per-step timeout (default 1800)
      --retries N     retries per step (default 2)
      --redo          ignore .done stamps and re-download
      --keep-going    run a scenario's remaining steps even after one fails
      --install-deps  pip install the union of scripts/requirements.txt first
  -n, --dry-run       print what would run
  -l, --list          list the selected scenarios and exit
  -h, --help          this text
EOF
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    -s|--scenario) WANT_SCENARIOS+=("$2"); shift 2 ;;
    -t|--tier)     TIER="$2"; shift 2 ;;
    -d|--domain)   DOMAIN="$2"; shift 2 ;;
    -j|--jobs)     JOBS="$2"; shift 2 ;;
    -o|--only)     ONLY="$2"; shift 2 ;;
    --extra)       EXTRA="$2"; shift 2 ;;
    --until)       UNTIL="$2"; shift 2 ;;
    --timeout)     TIMEOUT="$2"; shift 2 ;;
    --retries)     RETRIES="$2"; shift 2 ;;
    --redo)        REDO=1; shift ;;
    --install-deps) INSTALL_DEPS=1; shift ;;
    --keep-going)  KEEP_GOING=1; shift ;;
    -n|--dry-run)  DRY_RUN=1; shift ;;
    -l|--list)     LIST_ONLY=1; shift ;;
    -h|--help)     usage 0 ;;
    *) log "unknown option: $1"; usage 2 ;;
  esac
done
LIST_ONLY="${LIST_ONLY:-0}"

# --- preflight -------------------------------------------------------------

[ -n "$PY" ] && [ -x "$PY" ] || die "no python found; set TIMESAGE_PYTHON"
[ -d "$CODE_ROOT" ] || die "missing $CODE_ROOT"

if [ "$INSTALL_DEPS" = 1 ]; then
  log "installing: $REQUIREMENTS"
  # shellcheck disable=SC2086
  "$PY" -m pip install -q $REQUIREMENTS || die "dependency install failed"
fi

missing_mods=$("$PY" - <<'EOF'
import importlib
need = {"bs4": "beautifulsoup4", "lxml": "lxml", "pdfplumber": "pdfplumber",
        "pypdf": "pypdf", "yaml": "PyYAML", "requests": "requests", "xlrd": "xlrd"}
print(" ".join(pkg for mod, pkg in need.items()
                if importlib.util.find_spec(mod) is None))
EOF
)
if [ -n "$missing_mods" ]; then
  log "WARNING: missing packages: $missing_mods"
  log "         some scenarios will fail; re-run with --install-deps"
fi

# --- scenario selection ----------------------------------------------------

mapfile -t ALL < <(
  find "$CODE_ROOT" -mindepth 3 -maxdepth 3 -type d | sort
)
declare -a SELECTED=()
for dir in "${ALL[@]}"; do
  id="$(basename "$dir")"
  tier="$(basename "$(dirname "$(dirname "$dir")")")"
  domain="$(basename "$(dirname "$dir")")"
  [ -n "$TIER" ] && [ "$tier" != "$TIER" ] && continue
  [ -n "$DOMAIN" ] && [ "$domain" != "$DOMAIN" ] && continue
  if [ ${#WANT_SCENARIOS[@]} -gt 0 ]; then
    found=0
    for want in "${WANT_SCENARIOS[@]}"; do [ "$want" = "$id" ] && found=1; done
    [ "$found" = 0 ] && continue
  fi
  [ -f "$dir/scripts/download.py" ] || continue
  SELECTED+=("$dir")
done

[ ${#SELECTED[@]} -gt 0 ] || die "no scenarios matched"

if [ "$LIST_ONLY" = 1 ]; then
  for dir in "${SELECTED[@]}"; do basename "$dir"; done
  exit 0
fi

mkdir -p "$LOG_DIR"

# --- one scenario ----------------------------------------------------------

run_scenario() {
  local dir="$1"
  local id; id="$(basename "$dir")"
  local script="$dir/scripts/download.py"
  local logfile="$LOG_DIR/$id.log"
  local stamp="$LOG_DIR/$id.done"

  if [ "$REDO" = 0 ] && [ -f "$stamp" ]; then
    printf 'SKIP\t%s\tstamped %s\n' "$id" "$(cat "$stamp")"
    return 0
  fi

  local key="${NEEDS_KEY[$id]:-}"
  if [ -n "$key" ] && [ -z "${!key:-}" ]; then
    printf 'SKIP\t%s\t%s is not set\n' "$id" "$key"
    return 0
  fi

  # Ask what each step wants; the parsers disagree and the range comes from
  # scenario.json.
  local plan
  if ! plan="$("$PY" "$TOOLS_DIR/scenario_cmd.py" download "$id" \
                ${ONLY:+--only "$ONLY"} ${UNTIL:+--until "$UNTIL"} \
                --extra "$EXTRA" 2>>"$logfile")"; then
    printf 'FAIL\t%s\tcould not resolve arguments (see %s)\n' "$id" "$logfile"
    return 1
  fi

  : >"$logfile"
  local rc=0 data_dir produced
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local step; step="${line%%$'\t'*}"
    local rest; rest="${line#"$step"}"
    # shellcheck disable=SC2206
    local argv=(); [ -n "$rest" ] && IFS=$'\t' read -r -a argv <<<"${rest#$'\t'}"

    if [ "$DRY_RUN" = 1 ]; then
      if [ "${step:0:1}" = "@" ]; then
        printf 'DRY \t%s\t%s %s %s\n' "$id" "$PY" "$dir/scripts/${step:1}" "${argv[*]}"
      else
        printf 'DRY \t%s\t%s %s %s %s\n' "$id" "$PY" "$script" "$step" "${argv[*]}"
      fi
      continue
    fi

    local attempt=0 ok=0 target sub code backoff
    while [ "$attempt" -le "$RETRIES" ]; do
      attempt=$((attempt + 1))
      # A step named @foo.py is a specialised downloader invoked directly;
      # anything else is a step of the merged download.py.
      if [ "${step:0:1}" = "@" ]; then
        target="$dir/scripts/${step:1}"; sub=()
      else
        target="$script"; sub=("$step")
      fi
      {
        printf '\n=== %s %s (attempt %d/%d) %s ===\n' \
               "$id" "$step" "$attempt" "$((RETRIES + 1))" "$(date -Is)"
        printf '%s %s %s %s\n' "$PY" "$target" "${sub[*]-}" "${argv[*]}"
      } >>"$logfile"
      # Capture the status directly. Reading $? after an `if cmd; then …; fi`
      # yields the status of the *compound* command — 0 when the condition
      # failed and there is no else branch — so every failure logged "exit 0".
      timeout "$TIMEOUT" "$PY" "$target" "${sub[@]}" "${argv[@]}" >>"$logfile" 2>&1
      code=$?
      if [ "$code" -eq 0 ]; then
        ok=1; break
      fi
      printf '[attempt %d] exit %d\n' "$attempt" "$code" >>"$logfile"
      # Exponential, not linear. The old attempt*5 gave 5s and 10s, which is
      # nothing to a Wayback CDX rate limit — that endpoint was answering in
      # 25s under load and needs minutes, not seconds.
      if [ "$attempt" -le "$RETRIES" ]; then
        backoff=$((30 * (1 << (attempt - 1))))
        printf '[backoff] sleeping %ds before retry\n' "$backoff" >>"$logfile"
        sleep "$backoff"
      fi
    done
    if [ "$ok" = 0 ]; then
      printf 'FAIL\t%s\tstep %s (see %s)\n' "$id" "$step" "$logfile"
      rc=1
      # Stopping here is right when the next step consumes this one's output,
      # and wrong when they are independent: a NOAA scenario whose timeseries
      # step "fails" on three permanently-404 months lost its whole gt step too,
      # and with it 28 files it could have had. --keep-going trades that for the
      # risk of a dependent step failing noisily right after.
      [ "$KEEP_GOING" = 1 ] || break
    fi
  done <<<"$plan"

  # A zero exit is not proof of a download. eia_wpsr_weekly_petroleum_brief
  # logged HTTP 404 for every single PDF, returned 0, and was stamped done with
  # an empty directory — the failure mode that is worse than a loud one because
  # nothing surfaces it. Check the output, not just the status.
  if [ "$DRY_RUN" = 0 ] && [ "$rc" = 0 ]; then
    local data_dir="$TIMESAGE_DATA_ROOT/${dir#"$CODE_ROOT/"}"
    local produced
    produced=$(find "$data_dir" -type f 2>/dev/null | wc -l)
    if [ "$produced" -eq 0 ]; then
      printf 'FAIL\t%s\texited 0 but produced no files (see %s)\n' "$id" "$logfile"
      printf '\n[postcondition] exit 0 with an empty %s\n' "$data_dir" >>"$logfile"
      return 1
    fi
  fi

  if [ "$DRY_RUN" = 0 ] && [ "$rc" = 0 ]; then
    date -Is >"$stamp"
    printf 'OK  \t%s\t%s files\n' "$id" "$produced"
  fi
  return "$rc"
}
export -f run_scenario die log
export PY REPO_ROOT TOOLS_DIR CODE_ROOT LOG_DIR ONLY EXTRA UNTIL TIMEOUT RETRIES DRY_RUN REDO KEEP_GOING

# --- drive -----------------------------------------------------------------

started="$(date -Is)"
log "downloading ${#SELECTED[@]} scenarios · jobs=$JOBS · timeout=${TIMEOUT}s · started $started"
[ "$JOBS" -gt 1 ] && log "NOTE: -j $JOBS issues parallel requests to publisher servers"

results="$(mktemp)"
trap 'rm -f "$results"' EXIT

if [ "$JOBS" -le 1 ]; then
  for dir in "${SELECTED[@]}"; do
    run_scenario "$dir" | tee -a "$results"
  done
else
  # NEEDS_KEY cannot cross the xargs boundary as an associative array, so the
  # key check is re-done in the child through the environment it already reads.
  printf '%s\n' "${SELECTED[@]}" \
    | xargs -P "$JOBS" -I{} bash -c 'run_scenario "$@"' _ {} \
    | tee -a "$results"
fi

# --- summary ---------------------------------------------------------------

ok=$(grep -c '^OK'   "$results" || true)
skip=$(grep -c '^SKIP' "$results" || true)
fail=$(grep -c '^FAIL' "$results" || true)

printf '\n%s\n' "----------------------------------------------------------------"
printf 'selected %d · ok %d · skipped %d · failed %d\n' \
       "${#SELECTED[@]}" "$ok" "$skip" "$fail"
if [ "$skip" -gt 0 ]; then
  printf '\nskipped:\n'; grep '^SKIP' "$results" | cut -f2,3 | sed 's/^/  /'
fi
if [ "$fail" -gt 0 ]; then
  printf '\nfailed:\n'; grep '^FAIL' "$results" | cut -f2,3 | sed 's/^/  /'
  printf '\nlogs in %s — re-run to retry only what failed\n' "$LOG_DIR"
fi
printf 'started %s · finished %s\n' "$started" "$(date -Is)"

[ "$fail" -eq 0 ]
