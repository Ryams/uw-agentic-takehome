"""Component + system versioning (D10).

* Each core component owns a set of files (globs). Its *version* is an integer
  starting at 0 that increments whenever the content hash of those files changes.
* `versions/components.json` is the committed manifest `{component: {version,
  content_hash, files}}`. A pre-commit hook (`python -m uw_agent.versioning bump
  --stage`) keeps it current; `tests/test_versions.py` fails if it is stale.
* The *system version* is the git short hash, plus `+dirty-<fingerprint>` when
  tracked code/data differs from HEAD, so uncommitted runs are still identifiable.
* `system_versions` (SQLite) maps system version -> component versions; the same
  mapping for any past commit is `git show <commit>:versions/components.json`.

Stdlib only (the hook runs it without the project venv).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = "versions/components.json"
PROTOCOL_MANIFEST = "sim-harness/protocols/manifest.json"

# component -> file globs (relative to repo root). Files that don't exist yet are
# fine: the component hashes as empty until they appear (then its version bumps).
STATIC_COMPONENTS: dict[str, list[str]] = {
    "normalizer": ["uw_agent/normalize.py"],
    "resolver": ["uw_agent/resolution.py", "sim-harness/shared/field_resolution.json"],
    "protocol_engine": ["uw_agent/protocols/engine.py"],
    "protocol_manifest": [PROTOCOL_MANIFEST],
    "field_registry": ["sim-harness/shared/field_registry.json"],
    "lookup_tools": ["uw_agent/tools/*.py"],
    "llm_client": ["uw_agent/llm.py"],
    "evidence_interpreter": ["uw_agent/interpreter.py", "uw_agent/prompts/interpreter*.md"],
    "email_composer": ["uw_agent/composer.py", "uw_agent/prompts/composer*.md"],
    "summarizer": ["uw_agent/summarizer.py", "uw_agent/prompts/summar*.md"],
    "orchestrator": ["uw_agent/orchestrator.py"],
    "grader": ["evals/grader.py"],
    # Eval set: the (modified) lead generator determines what a seed means.
    "leadgen_generator": [
        "sim-harness/leadgen/*.py",
        "sim-harness/leadgen/generator_config.yaml",
        "sim-harness/shared/schema.py",
    ],
}


def component_files(root: Path = ROOT) -> dict[str, list[str]]:
    """Static components plus one `protocol:<name>` per protocol in the manifest."""
    comps = dict(STATIC_COMPONENTS)
    pm = root / PROTOCOL_MANIFEST
    if pm.exists():
        for entry in json.loads(pm.read_text())["protocols"]:
            comps[f"protocol:{entry['protocol']}"] = [f"sim-harness/protocols/{entry['file']}"]
    return comps


def _resolve(root: Path, globs: list[str]) -> list[str]:
    found: set[str] = set()
    for g in globs:
        for p in root.glob(g):
            if p.is_file() and "__pycache__" not in p.parts:
                found.add(p.relative_to(root).as_posix())
    return sorted(found)


def hash_files(root: Path, rel_files: list[str]) -> str:
    h = hashlib.sha256()
    for rel in rel_files:
        h.update(rel.encode() + b"\0" + (root / rel).read_bytes() + b"\0")
    return h.hexdigest()[:12]


def live_components(root: Path = ROOT, registry: Optional[dict[str, list[str]]] = None) -> dict[str, dict[str, Any]]:
    """Current content hash + resolved files for every component (no versions yet)."""
    reg = registry if registry is not None else component_files(root)
    out = {}
    for name, globs in sorted(reg.items()):
        files = _resolve(root, globs)
        out[name] = {"content_hash": hash_files(root, files) if files else "empty", "files": files}
    return out


def load_manifest(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    p = root / MANIFEST_PATH
    return json.loads(p.read_text()) if p.exists() else {}


def bumped_manifest(old: dict[str, dict[str, Any]], live: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """New component -> version 0; changed content hash -> version + 1; removed -> dropped."""
    new = {}
    for name, cur in live.items():
        prev = old.get(name)
        if prev is None:
            version = 0
        elif prev["content_hash"] != cur["content_hash"]:
            version = prev["version"] + 1
        else:
            version = prev["version"]
        new[name] = {"version": version, "content_hash": cur["content_hash"], "files": cur["files"]}
    return new


def write_manifest(manifest: dict[str, Any], root: Path = ROOT) -> None:
    p = root / MANIFEST_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def stale_components(root: Path = ROOT) -> list[str]:
    """Components whose live hash differs from the committed manifest (or are missing)."""
    old, live = load_manifest(root), live_components(root)
    names = set(old) | set(live)
    return sorted(n for n in names
                  if n not in old or n not in live or old[n]["content_hash"] != live[n]["content_hash"])


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
        return r.stdout.strip()
    except Exception:
        return None


def system_version(root: Path = ROOT) -> dict[str, Any]:
    """{system_version, git_commit, dirty, components: {name: {version, content_hash, dirty}}}.

    Component versions come from the committed manifest. A component whose live hash
    differs from the manifest is reported as `<version>+dirty` with its live hash.
    """
    manifest, live = load_manifest(root), live_components(root)
    components = {}
    for name, cur in live.items():
        m = manifest.get(name)
        dirty = m is None or m["content_hash"] != cur["content_hash"]
        components[name] = {
            "version": f"{m['version'] if m else 0}+dirty" if dirty else m["version"],
            "content_hash": cur["content_hash"],
            "dirty": dirty,
        }
    commit = _git(root, "rev-parse", "--short", "HEAD")
    status = _git(root, "status", "--porcelain", "--", "uw_agent", "sim-harness", "evals", "versions")
    tree_dirty = bool(status) or any(c["dirty"] for c in components.values())
    fingerprint = hashlib.sha256(
        json.dumps({n: c["content_hash"] for n, c in components.items()}, sort_keys=True).encode()
    ).hexdigest()[:8]
    if commit is None:  # no git: fall back to the component fingerprint
        version = f"nogit-{fingerprint}"
    else:
        version = f"{commit}+dirty-{fingerprint}" if tree_dirty else commit
    return {"system_version": version, "git_commit": commit, "dirty": tree_dirty, "components": components}


# --- SQLite registry (system version -> component versions) ----------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS system_versions (
    system_version TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    git_commit     TEXT,
    dirty          INTEGER NOT NULL,
    components_json TEXT NOT NULL
)"""


def register_system_version(conn: sqlite3.Connection, sv: Optional[dict[str, Any]] = None,
                            root: Path = ROOT) -> dict[str, Any]:
    """Idempotently record the current system version and its component versions."""
    sv = sv or system_version(root)
    conn.execute(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO system_versions VALUES (?,?,?,?,?)",
        (sv["system_version"], datetime.now(timezone.utc).isoformat(timespec="seconds"),
         sv["git_commit"], int(sv["dirty"]), json.dumps(sv["components"], sort_keys=True)),
    )
    conn.commit()
    return sv


# --- CLI (pre-commit hook) --------------------------------------------------

def _cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="uw_agent.versioning")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bump", help="recompute hashes, bump changed components, rewrite the manifest")
    b.add_argument("--stage", action="store_true", help="git add the manifest (pre-commit hook)")
    sub.add_parser("check", help="exit 1 if the manifest is stale")
    sub.add_parser("show", help="print the current system version")
    args = ap.parse_args(argv)

    if args.cmd == "show":
        print(json.dumps(system_version(), indent=2))
        return 0
    if args.cmd == "check":
        stale = stale_components()
        if stale:
            print("stale version manifest for:", ", ".join(stale), file=sys.stderr)
            return 1
        return 0
    old = load_manifest()
    new = bumped_manifest(old, live_components())
    if new != old:
        write_manifest(new)
        changed = [f"{n} {old[n]['version']}->{new[n]['version']}" for n in new
                   if n in old and old[n]["version"] != new[n]["version"]]
        added = [n for n in new if n not in old]
        print("versions updated:", ", ".join(changed + [f"{n} (new, v0)" for n in added]))
        if args.stage:
            _git(ROOT, "add", MANIFEST_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
