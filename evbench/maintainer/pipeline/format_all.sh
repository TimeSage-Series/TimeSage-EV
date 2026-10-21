#!/usr/bin/env bash
#
# Convert every scenario's downloaded source/ into per-period instances.
#
#   evbench/maintainer/pipeline/format_all.sh                    # all 60, one at a time
#   evbench/maintainer/pipeline/format_all.sh -t easy            # one tier
#   evbench/maintainer/pipeline/format_all.sh -s cboe_vix_volatility_regime_state
#   evbench/maintainer/pipeline/format_all.sh --with-ground-truth
#   evbench/maintainer/pipeline/format_all.sh --until 2026-10-11   # extend past the reference periods
#   evbench/maintainer/pipeline/format_all.sh --dry-run
#
# Produces instances/<period>/{timeseries.csv, gt_evidence.md}, then writes
# instance.json (the question template's placeholder values) with
# template_vars.py. ground_truth.json is discarded unless --with-ground-truth
# is given: format.py and evbench/tasks/.../answer_schema.json disagree about
# the answer contract for all 20 easy scenarios — the schema requires a
# `report` field the scripts never emit, and the scripts emit an `as_of_date`
# the schema does not declare. Writing ground truth before that is settled
# would change what gets scored.
#
# Unlike downloading, this touches no network, so it is safe to parallelise.
#
set -uo pipefail

TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_ROOT="$(dirname "$TOOLS_DIR")"
REPO_ROOT="$(cd "$CODE_ROOT/../.." && pwd)"
LOG_DIR="$REPO_ROOT/logs/format"
PY="${TIMESAGE_PYTHON:-$REPO_ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
DATA_ROOT="${TIMESAGE_DATA_ROOT:-$REPO_ROOT/scenarios_hf}"

JOBS=1
TIMEOUT=1800
WITH_GT=0
DRY_RUN=0
REDO=0
KEEP_GOING=1
UNTIL=""
TIER=""
DOMAIN=""
declare -a WANT=()

die() { printf '%s\n' "$*" >&2; exit 1; }
log() { printf '%s\n' "$*" >&2; }

usage() {
  sed -n '2,/^set -uo/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//; $d'
  cat >&2 <<'EOF'
Options:
  -s, --scenario ID       only this scenario (repeatable)
  -t, --tier TIER         easy | middle | hard
  -d, --domain DOMAIN     one domain
  -j, --jobs N            scenarios in parallel (default 1; safe to raise)
      --with-ground-truth also keep ground_truth.json
      --until DATE        extend each scenario's end bound to this date
      --timeout SEC       per-step timeout (default 1800)
      --redo              ignore .done stamps
      --stop-on-error     abort a scenario's remaining steps after one fails
  -n, --dry-run           print what would run
  -l, --list              list the selected scenarios
  -h, --help              this text
EOF
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    -s|--scenario) WANT+=("$2"); shift 2 ;;
    -t|--tier)     TIER="$2"; shift 2 ;;
    -d|--domain)   DOMAIN="$2"; shift 2 ;;
    -j|--jobs)     JOBS="$2"; shift 2 ;;
    --with-ground-truth) WITH_GT=1; shift ;;
    --until)       UNTIL="$2"; shift 2 ;;
    --timeout)     TIMEOUT="$2"; shift 2 ;;
    --redo)        REDO=1; shift ;;
    --stop-on-error) KEEP_GOING=0; shift ;;
    -n|--dry-run)  DRY_RUN=1; shift ;;
    -l|--list)     LIST_ONLY=1; shift ;;
    -h|--help)     usage 0 ;;
    *) log "unknown option: $1"; usage 2 ;;
  esac
done
LIST_ONLY="${LIST_ONLY:-0}"

[ -n "$PY" ] && [ -x "$PY" ] || die "no python found; set TIMESAGE_PYTHON"
[ -d "$CODE_ROOT" ] || die "missing $CODE_ROOT"
[ -d "$DATA_ROOT" ] || die "missing data root $DATA_ROOT — run download_all.sh first"

mapfile -t ALL < <(find "$CODE_ROOT" -mindepth 3 -maxdepth 3 -type d | sort)
declare -a SELECTED=()
for dir in "${ALL[@]}"; do
  id="$(basename "$dir")"
  tier="$(basename "$(dirname "$(dirname "$dir")")")"
  domain="$(basename "$(dirname "$dir")")"
  [ -n "$TIER" ] && [ "$tier" != "$TIER" ] && continue
  [ -n "$DOMAIN" ] && [ "$domain" != "$DOMAIN" ] && continue
  if [ ${#WANT[@]} -gt 0 ]; then
    hit=0; for w in "${WANT[@]}"; do [ "$w" = "$id" ] && hit=1; done
    [ "$hit" = 0 ] && continue
  fi
  [ -f "$dir/scripts/format.py" ] || continue
  # Nothing to convert without downloaded source.
  [ -d "$DATA_ROOT/${dir#"$CODE_ROOT/"}/source" ] || continue
  SELECTED+=("$dir")
done
[ ${#SELECTED[@]} -gt 0 ] || die "no scenarios matched (is source/ downloaded?)"

if [ "$LIST_ONLY" = 1 ]; then
  for dir in "${SELECTED[@]}"; do basename "$dir"; done; exit 0
fi
mkdir -p "$LOG_DIR"

run_scenario() {
  local dir="$1"
  local id; id="$(basename "$dir")"
  local script="$dir/scripts/format.py"
  local logfile="$LOG_DIR/$id.log"
  local stamp="$LOG_DIR/$id.done"
  local data="$DATA_ROOT/${dir#"$CODE_ROOT/"}"

  if [ "$REDO" = 0 ] && [ -f "$stamp" ]; then
    printf 'SKIP\t%s\tstamped %s\n' "$id" "$(cat "$stamp")"; return 0
  fi

  local plan qplan
  if ! plan="$("$PY" "$TOOLS_DIR/scenario_cmd.py" format "$id" \
                ${UNTIL:+--until "$UNTIL"} 2>>"$logfile")"; then
    printf 'FAIL\t%s\tcould not resolve arguments (see %s)\n' "$id" "$logfile"; return 1
  fi
  if [ -f "$dir/scripts/template_vars.py" ]; then
    if ! qplan="$("$PY" "$TOOLS_DIR/scenario_cmd.py" vars "$id" \
                   ${UNTIL:+--until "$UNTIL"} 2>>"$logfile")"; then
      printf 'FAIL\t%s\tcould not resolve template-vars arguments (see %s)\n' "$id" "$logfile"; return 1
    fi
    plan+=$'\n'"$qplan"
  fi

  : >"$logfile"
  local rc=0 code
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local step="${line%%$'\t'*}"
    local rest="${line#"$step"}"
    local argv=(); [ -n "$rest" ] && IFS=$'\t' read -r -a argv <<<"${rest#$'\t'}"
    [ "${step:0:1}" = "@" ] && continue          # aux scripts are download-side

    # The vars step is its own script and takes no step argument.
    local cmd=("$script" "$step")
    [ "$step" = vars ] && cmd=("$dir/scripts/template_vars.py")

    if [ "$DRY_RUN" = 1 ]; then
      printf 'DRY \t%s\t%s %s\n' "$id" "${cmd[*]}" "${argv[*]}"; continue
    fi

    printf '\n=== %s %s %s ===\n' "$id" "$step" "$(date -Is)" >>"$logfile"
    TIMESAGE_DATA_ROOT="$DATA_ROOT" timeout "$TIMEOUT" "$PY" "${cmd[@]}" "${argv[@]}" >>"$logfile" 2>&1
    code=$?
    if [ "$code" -ne 0 ]; then
      printf 'FAIL\t%s\tstep %s exit %d (see %s)\n' "$id" "$step" "$code" "$logfile"
      rc=1
      [ "$KEEP_GOING" = 1 ] || break
    fi
  done <<<"$plan"

  [ "$DRY_RUN" = 1 ] && return 0

  # Ground truth is computed by the same step that writes the evidence, so it is
  # produced and then removed rather than skipped.
  if [ "$WITH_GT" = 0 ]; then
    find "$data/instances" -name ground_truth.json -delete 2>/dev/null
  fi

  # A zero exit is not proof of output. Check for the two artifacts this tool
  # exists to produce.
  local n_csv n_ev
  n_csv=$(find "$data/instances" -name timeseries.csv 2>/dev/null | wc -l)
  n_ev=$(find "$data/instances" -name gt_evidence.md 2>/dev/null | wc -l)
  if [ "$n_csv" -eq 0 ] && [ "$n_ev" -eq 0 ]; then
    printf 'FAIL\t%s\tproduced no csv and no evidence (see %s)\n' "$id" "$logfile"
    return 1
  fi

  if [ "$rc" = 0 ]; then
    date -Is >"$stamp"
    printf 'OK  \t%s\t%s csv, %s evidence\n' "$id" "$n_csv" "$n_ev"
  else
    printf 'PART\t%s\t%s csv, %s evidence (a step failed)\n' "$id" "$n_csv" "$n_ev"
  fi
  return "$rc"
}
export -f run_scenario
export PY REPO_ROOT TOOLS_DIR CODE_ROOT DATA_ROOT LOG_DIR TIMEOUT DRY_RUN REDO KEEP_GOING WITH_GT UNTIL

started="$(date -Is)"
log "formatting ${#SELECTED[@]} scenarios · jobs=$JOBS · ground_truth=$([ "$WITH_GT" = 1 ] && echo keep || echo discard)"
results="$(mktemp)"; trap 'rm -f "$results"' EXIT

if [ "$JOBS" -le 1 ]; then
  for dir in "${SELECTED[@]}"; do run_scenario "$dir" | tee -a "$results"; done
else
  printf '%s\n' "${SELECTED[@]}" \
    | xargs -P "$JOBS" -I{} bash -c 'run_scenario "$@"' _ {} | tee -a "$results"
fi

ok=$(grep -c '^OK'   "$results" || true)
part=$(grep -c '^PART' "$results" || true)
fail=$(grep -c '^FAIL' "$results" || true)
printf '\n%s\n' "----------------------------------------------------------------"
printf 'selected %d · ok %d · partial %d · failed %d\n' \
       "${#SELECTED[@]}" "$ok" "$part" "$fail"
[ "$fail" -gt 0 ] && { printf '\nfailed:\n'; grep '^FAIL' "$results" | cut -f2,3 | sed 's/^/  /'; }
[ "$part" -gt 0 ] && { printf '\npartial:\n'; grep '^PART' "$results" | cut -f2,3 | sed 's/^/  /'; }
printf 'started %s · finished %s\n' "$started" "$(date -Is)"
[ "$fail" -eq 0 ]
