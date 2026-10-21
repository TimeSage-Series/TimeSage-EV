"""Skill library I/O for timesage_agent.

Each skill is a pair of files on disk:

    <skill_dir>/<name>.md   ← human-readable docs + YAML frontmatter (metadata)
    <skill_dir>/<name>.py   ← executable code; defines `def skill(...)`

Public API:

    save_skill(skill_dir, name, description, code,
               inputs_schema, output_type,
               notes="", tags=None, inducted_from=None)
        → Path of the saved .md (raises on validation failure)

    list_skills(skill_dir) → list[(name, description)]
        Cheap index used to seed the agent prompt.

    load_skill_markdown(skill_dir, name) → str
        The markdown body (post-frontmatter) of a saved skill.

    parse_frontmatter(md_path) → dict
        Just the metadata dict.

    build_skill_tool(md_path) → smolagents.Tool
        Loads the companion .py and wraps it in a dynamically-constructed
        Tool class with the metadata from the .md as the schema.

    build_all_skill_tools(skill_dir) → list[Tool]
        Convenience: build_skill_tool for every (.md, .py) pair in dir.

No external state — all I/O is plain files, no DB. Each save is two atomic
writes (.md + .py) under the per-sweep skill dir.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path
from typing import Any, Optional

import yaml

# Imported lazily inside build_skill_tool so this module is import-safe
# without smolagents installed (useful for unit tests of pure I/O).
# from smolagents import Tool


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


# ---------------------------------------------------------------------------
# Frontmatter parsing / emission
# ---------------------------------------------------------------------------

def parse_frontmatter(md_path: Path) -> dict:
    """Return the YAML frontmatter dict for a skill markdown file.

    Raises ValueError if the file has no frontmatter or invalid YAML.
    """
    text = Path(md_path).read_text()
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"{md_path}: missing YAML frontmatter (expected leading '---\\n…\\n---')")
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"{md_path}: frontmatter must be a mapping, got {type(meta).__name__}")
    return meta


def _markdown_body(md_path: Path) -> str:
    """Return everything after the closing '---' line."""
    text = Path(md_path).read_text()
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return text
    return m.group(2)


def _emit_frontmatter(meta: dict) -> str:
    """Render metadata as a YAML frontmatter block (with '---' fences)."""
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True,
                                default_flow_style=False).rstrip()
    return f"---\n{yaml_text}\n---\n"


# ---------------------------------------------------------------------------
# Save / load / list
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _SLUG_RE.match(name):
        raise ValueError(
            f"skill name must be snake_case ASCII (^[a-z0-9][a-z0-9_]*$); "
            f"got {name!r}"
        )


def _validate_skill_function(code: str, inputs_schema: dict) -> None:
    """Three-gate validation:

      Gate 1 (ast):        code parses + defines a top-level `def skill(...)`.
      Gate 2 (import):     the module actually loads — catches missing
                            module-level imports / NameError at import time
                            (e.g., `from nonexistent import x`).
      Gate 3 (signature):  the `skill` function's positional+keyword parameter
                            names match the `inputs_schema` keys, and any
                            parameter declared `nullable=True` has a default.

    Each gate raises ValueError with a descriptive message and is run in
    order — we abort on the first failure (cheaper than re-checking later).

    Note: this does NOT execute `skill(...)` itself. A smoke-call against
    real inputs is a separate concern (Gate 3 in the auto-induct flow,
    which has the period's sandbox cwd available).
    """
    import inspect
    import tempfile
    import importlib.util
    import os as _os

    # Gate 1 — ast
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(
            f"skill code is not valid Python: {exc.msg} (line {exc.lineno})"
        ) from exc
    has_skill = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "skill"
        for node in tree.body
    )
    if not has_skill:
        raise ValueError(
            "skill code must define a top-level function named exactly `skill(...)`"
        )

    # Gate 2 — import. Write to a temp .py and exec via importlib so we
    # catch module-level ImportError, NameError, syntactically-valid-but-
    # logically-broken module bodies, etc.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w",
                                          delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = f.name
        spec = importlib.util.spec_from_file_location("_timesage_skill_check", tmp_path)
        if spec is None or spec.loader is None:
            raise ValueError("could not build module spec for skill code")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:                                       # noqa: BLE001
            raise ValueError(
                f"skill module failed to import: {type(exc).__name__}: {exc}"
            ) from exc
        skill_fn = getattr(mod, "skill", None)
        if not callable(skill_fn):
            raise ValueError("`skill` symbol exists but is not callable")
    finally:
        if tmp_path is not None and _os.path.exists(tmp_path):
            _os.unlink(tmp_path)

    # Gate 3 — signature ↔ inputs_schema match
    try:
        sig = inspect.signature(skill_fn)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"could not inspect skill signature: {exc}") from exc

    # Allow `**kwargs` to mean "accept anything declared in inputs_schema".
    has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD
                          for p in sig.parameters.values())
    if not has_var_keyword:
        sig_param_names = {
            name for name, p in sig.parameters.items()
            if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                          inspect.Parameter.KEYWORD_ONLY)
        }
        schema_keys = set(inputs_schema.keys())
        missing_in_sig = schema_keys - sig_param_names
        extra_in_sig = {
            n for n in sig_param_names - schema_keys
            if sig.parameters[n].default is inspect.Parameter.empty
        }
        if missing_in_sig:
            raise ValueError(
                f"inputs_schema declares params {sorted(missing_in_sig)} but "
                f"skill() doesn't accept them"
            )
        if extra_in_sig:
            raise ValueError(
                f"skill() requires params {sorted(extra_in_sig)} that are "
                f"not in inputs_schema (and have no default value)"
            )

    # Nullable params should have a default so the dynamic-tool wrapper's
    # "drop None to use default" trick works.
    for name, meta in inputs_schema.items():
        if not isinstance(meta, dict): continue
        if not meta.get("nullable"): continue
        if name not in sig.parameters: continue
        if sig.parameters[name].default is inspect.Parameter.empty:
            raise ValueError(
                f"inputs_schema marks `{name}` as nullable=True but the "
                f"skill function has no default for it"
            )


def save_skill(skill_dir: Path,
               *,
               name: str,
               description: str,
               code: str,
               inputs_schema: dict,
               output_type: str,
               notes: str = "",
               tags: Optional[list[str]] = None,
               inducted_from: Optional[dict] = None) -> Path:
    """Persist a skill as a (<name>.md, <name>.py) pair.

    Validation:
      * name must match ^[a-z0-9][a-z0-9_]*$
      * description must be ≤ 160 chars (soft cap, hard-fail anything longer)
      * code must parse AND define a top-level function `skill`
      * inputs_schema must be a dict
      * output_type must be a non-empty string

    Overwrites any existing skill with the same name.
    Returns the .md path on success.
    """
    skill_dir = Path(skill_dir)
    _validate_name(name)
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-empty string")
    if len(description) > 160:
        raise ValueError(
            f"description must be ≤ 160 chars (got {len(description)}); "
            "put longer notes in the `notes` field instead"
        )
    if not isinstance(inputs_schema, dict):
        raise ValueError(f"inputs_schema must be a dict, got {type(inputs_schema).__name__}")
    bad_keys = [k for k in inputs_schema if not (isinstance(k, str) and k.isidentifier())]
    if bad_keys:
        raise ValueError(
            f"inputs_schema keys must be valid Python identifiers; got {bad_keys}"
        )
    if not isinstance(output_type, str) or not output_type.strip():
        raise ValueError("output_type must be a non-empty string")
    _validate_skill_function(code, inputs_schema)

    meta = {
        "name":         name,
        "description":  description.strip(),
        "tags":         list(tags or []),
        "inputs_schema": inputs_schema,
        "output_type":  output_type,
    }
    if inducted_from:
        meta["inducted_from"] = inducted_from

    skill_dir.mkdir(parents=True, exist_ok=True)
    md_path = skill_dir / f"{name}.md"
    py_path = skill_dir / f"{name}.py"

    body = "\n## Notes\n\n" + (notes.strip() or "(no notes)") + "\n\n## Code\n\n```python\n" + code.strip() + "\n```\n"
    md_path.write_text(_emit_frontmatter(meta) + body)
    py_path.write_text(code.rstrip() + "\n")
    return md_path


def list_skills(skill_dir: Path) -> list[tuple[str, str]]:
    """Return [(name, description), ...] for every valid skill in skill_dir.

    Silently skips files that fail to parse — we'd rather lose one bad
    skill than crash the whole agent.
    """
    skill_dir = Path(skill_dir)
    if not skill_dir.exists():
        return []
    out: list[tuple[str, str]] = []
    for md_path in sorted(skill_dir.glob("*.md")):
        try:
            meta = parse_frontmatter(md_path)
        except Exception:
            continue
        name = meta.get("name")
        desc = meta.get("description")
        py_path = md_path.with_suffix(".py")
        if not isinstance(name, str) or not isinstance(desc, str):
            continue
        if not py_path.exists():
            continue
        out.append((name, desc))
    return out


def load_skill_markdown(skill_dir: Path, name: str) -> str:
    """Return the markdown body (post-frontmatter) of skill `name`.

    Raises FileNotFoundError if missing.
    """
    md_path = Path(skill_dir) / f"{name}.md"
    if not md_path.exists():
        raise FileNotFoundError(f"skill not found: {md_path}")
    return _markdown_body(md_path)


# ---------------------------------------------------------------------------
# Dynamic Tool factory
# ---------------------------------------------------------------------------

def build_skill_tool(md_path: Path):
    """Load a saved skill and return a smolagents Tool instance.

    The Tool's name / description / inputs / output_type come from the
    .md frontmatter; its forward() invokes the `skill` function from the
    companion .py file.

    Raises ValueError if the skill is malformed.
    """
    from smolagents import Tool

    md_path = Path(md_path)
    meta = parse_frontmatter(md_path)
    name = meta.get("name")
    description = meta.get("description")
    inputs_schema = meta.get("inputs_schema") or {}
    output_type = meta.get("output_type") or "object"
    if not isinstance(name, str) or not isinstance(description, str):
        raise ValueError(f"{md_path}: missing name or description in frontmatter")

    py_path = md_path.with_suffix(".py")
    if not py_path.exists():
        raise ValueError(f"{md_path}: companion {py_path.name} not found")

    spec = importlib.util.spec_from_file_location(f"timesage_skill_{name}", py_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"{py_path}: could not build module spec")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # may raise: surface to caller
    fn = getattr(mod, "skill", None)
    if not callable(fn):
        raise ValueError(f"{py_path}: top-level `skill` function not found")

    # smolagents validates Tool subclasses by introspecting `forward()`'s
    # parameter names — they must literally match the keys of `inputs`. A
    # plain (self, **kwargs) won't pass. So we generate a tiny wrapper
    # whose signature reflects the inputs schema. Param names must be
    # valid Python identifiers (we accept whatever the skill author used).
    param_names = list(inputs_schema.keys())
    if not all(p.isidentifier() for p in param_names):
        raise ValueError(
            f"inputs_schema keys must be valid Python identifiers; got {param_names}"
        )
    # Optional params (nullable=True) get default=None in the wrapper.
    # If a None comes in for a nullable, we DROP it from the call so the
    # skill function's own default kicks in.
    sig_parts = []
    call_lines = ["    _kwargs = {}"]
    for p in param_names:
        nullable = bool((inputs_schema.get(p) or {}).get("nullable"))
        if nullable:
            sig_parts.append(f"{p}=None")
            call_lines.append(f"    if {p} is not None: _kwargs['{p}'] = {p}")
        else:
            sig_parts.append(p)
            call_lines.append(f"    _kwargs['{p}'] = {p}")
    src = (
        f"def forward(self, {', '.join(sig_parts)}):\n"
        + "\n".join(call_lines)
        + "\n    return _skill_fn(**_kwargs)\n"
    )
    ns: dict = {"_skill_fn": fn}
    exec(src, ns)
    forward_fn = ns["forward"]

    cls = type(
        f"Skill_{name}",
        (Tool,),
        {
            "name":        name,
            "description": description,
            "inputs":      inputs_schema,
            "output_type": output_type,
            "forward":     forward_fn,
        },
    )
    return cls()


def build_all_skill_tools(skill_dir: Path) -> list:
    """Build a Tool for every (.md, .py) pair in skill_dir. Skips broken ones."""
    skill_dir = Path(skill_dir)
    if not skill_dir.exists():
        return []
    out = []
    for md_path in sorted(skill_dir.glob("*.md")):
        py_path = md_path.with_suffix(".py")
        if not py_path.exists():
            continue
        try:
            out.append(build_skill_tool(md_path))
        except Exception:
            # Skip silently — a broken skill shouldn't take down the agent.
            continue
    return out


# ---------------------------------------------------------------------------
# Index block (for prepending to the agent prompt)
# ---------------------------------------------------------------------------

def build_skill_index_block(skill_dir: Path) -> str:
    """Render the 'Skill library' block that goes at the top of the
    agent prompt. Always non-empty — when the library is empty we still
    show a one-line nudge to induct, since first-period agents need to
    seed the library before reuse is even possible.
    """
    skills = list_skills(skill_dir)
    lines = ["## Skill library", ""]
    if not skills:
        lines.extend([
            "**The library is empty.** If during this period you write a small "
            "reusable function — e.g., a CSV loader for this dataset's exact "
            "schema, a date-to-period converter, a band/phase classifier — "
            "save it via `induct_skill(name=..., description=..., code=..., "
            "inputs_schema=..., output_type=...)` BEFORE you call "
            "`final_answer`. It will be auto-registered as a callable tool "
            "in subsequent periods so neither you nor a future agent has to "
            "re-derive the logic.",
            "",
            "Good induction candidates: anything you'd otherwise paste verbatim "
            "between periods. Bad candidates: scenario-specific one-off math, "
            "the literal final answer.",
        ])
    else:
        first_name = skills[0][0]
        lines.extend([
            "### ⚠️ INVOKE THESE SKILLS — they are already registered as tools",
            "",
            f"Each skill below is a callable tool. **Call it BY NAME from your "
            f"Python code**, e.g.:",
            "",
            f"    <code>",
            f"    # The skill `{first_name}` is registered — just call it.",
            f"    row = {first_name}()",
            f"    print(row)",
            f"    </code>",
            "",
            "**Do NOT re-implement the logic of a listed skill inline.** Reusing "
            "the skill is faster, less error-prone, and consistent with how "
            "the same problem was solved on prior periods. If the description "
            "is ambiguous, call `retrieve_skill(name=<id>)` to see the body.",
            "",
            "Saved skills (callable tools):",
        ])
        for name, desc in skills:
            lines.append(f"- **{name}** — {desc}")
        lines.extend([
            "",
            "If you find a NEW reusable idiom this period that's not above, "
            "save it with `induct_skill` so future periods can call it.",
        ])
    return "\n".join(lines) + "\n\n"
