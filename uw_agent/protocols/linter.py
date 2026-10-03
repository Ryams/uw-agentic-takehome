"""Protocol linter (D6/D9): checks every protocol file against the registry, outcomes and manifest.

Errors fail the build; warnings (e.g. uncovered select options) are informational.
Run: `python -m uw_agent.protocols.linter`   (exit 1 on errors)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import uw_agent.config  # noqa: F401  (puts sim-harness on sys.path for `shared`)
from shared import registry
from uw_agent.protocols.expr import ExprError, parse

PROTOCOLS_DIR = Path(__file__).resolve().parents[2] / "sim-harness" / "protocols"
DECISIONS = {"quote", "quote_with_conditions", "escalate", "decline", "cancel"}
STAGES = {"quote", "post_bind"}
NOT_IN_REGISTRY = "NOT IN REGISTRY"


def lint_manifest(directory: Path = PROTOCOLS_DIR) -> list[str]:
    errs: list[str] = []
    m = json.loads((directory / "manifest.json").read_text())["protocols"]
    names = [e["protocol"] for e in m]
    if len(names) != len(set(names)):
        errs.append("manifest: duplicate protocol names")
    files = {e["file"] for e in m}
    on_disk = {p.name for p in directory.glob("*.json") if p.name != "manifest.json"}
    for f in sorted(on_disk - files):
        errs.append(f"manifest: {f} is not listed in manifest.json")
    for f in sorted(files - on_disk):
        errs.append(f"manifest: lists {f} but the file does not exist")
    for e in m:
        for k in ("stage", "enabled", "order", "tags", "origin"):
            if k not in e:
                errs.append(f"manifest[{e['protocol']}]: missing {k}")
        if e.get("stage") not in STAGES:
            errs.append(f"manifest[{e['protocol']}]: bad stage {e.get('stage')!r}")
        o = e.get("origin", {})
        for k in ("source_image", "diagram", "split_from"):
            if k not in o:
                errs.append(f"manifest[{e['protocol']}]: origin missing {k}")
        if o.get("split_from") and not o.get("split_note"):
            errs.append(f"manifest[{e['protocol']}]: split without split_note")
        if o.get("source_image") and not (directory / o["source_image"]).exists():
            errs.append(f"manifest[{e['protocol']}]: source image {o['source_image']} not found")
    return errs


def _check_literals(expr, node_fields: set[str], where: str, nonreg: set[str], errs: list[str]) -> None:
    for fld, op, lit in expr.literals():
        if fld in nonreg or fld not in registry.field_names():
            continue
        kind = registry.meta(fld)["type"]["kind"]
        if kind == "select":
            opts = [str(o) for o in (registry.select_options(fld) or [])]
            if str(lit) not in opts:
                errs.append(f"{where}: {fld} compared with {lit!r}, not one of {opts}")
        elif kind == "toggle" and not isinstance(lit, bool):
            errs.append(f"{where}: toggle {fld} compared with non-boolean {lit!r}")
        elif kind in ("integer", "decimal") and (isinstance(lit, (bool, str))):
            errs.append(f"{where}: numeric {fld} compared with {lit!r}")


def lint_protocol(data: dict[str, Any], resolution: Optional[dict[str, Any]] = None) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings)."""
    errs: list[str] = []
    warns: list[str] = []
    name = data.get("protocol", "?")
    for k in ("protocol", "source_image", "applies_when", "outcomes", "stage"):
        if k not in data:
            errs.append(f"{name}: missing {k}")
    if errs:
        return errs, warns
    if "tree" not in data and "components" not in data:
        return [f"{name}: needs `tree` or `components`"], warns

    outcomes = data["outcomes"]
    for i, note in enumerate(data.get("sticky_notes", [])):
        if not isinstance(note, dict) or not str(note.get("text", "")).strip():
            errs.append(f"{name}: sticky_notes[{i}] needs non-empty text")
    for oid, o in outcomes.items():
        if o.get("decision") not in DECISIONS:
            errs.append(f"{name}: outcome {oid} has bad decision {o.get('decision')!r}")
    used: set[str] = set()
    all_fields = set(registry.field_names())
    nonreg: set[str] = set()  # fields declared NOT IN REGISTRY somewhere in this protocol
    seen_ids: set[str] = set()

    def collect_nonreg(n: dict[str, Any]) -> None:
        if str(n.get("field_status", "")).startswith(NOT_IN_REGISTRY):
            nonreg.update(n["fields"])
        for b in n.get("branches", []):
            if "outcome" not in b["then"]:
                collect_nonreg(b["then"])

    trees = [data["tree"]] if "tree" in data else [c["tree"] for c in data["components"]]
    for t in trees:
        collect_nonreg(t)

    try:
        ap = parse("true" if data["applies_when"] == "always" else data["applies_when"])
        for f in ap.fields():
            if f not in all_fields and f not in nonreg:
                errs.append(f"{name}: applies_when uses unknown field {f}")
        _check_literals(ap, set(), f"{name}.applies_when", nonreg, errs)
    except ExprError as e:
        errs.append(f"{name}: applies_when does not parse: {e}")

    def check_outcome(ref: Any, where: str) -> None:
        if not isinstance(ref, dict) or ref.get("outcome") not in outcomes:
            errs.append(f"{where}: outcome {ref!r} is not defined in outcomes")
        else:
            used.add(ref["outcome"])

    def walk(n: dict[str, Any]) -> None:
        nid = n.get("id", "?")
        where = f"{name}.{nid}"
        if nid in seen_ids:
            errs.append(f"{where}: duplicate node id")
        seen_ids.add(nid)
        for k in ("id", "question", "fields", "branches", "on_unexpected"):
            if not n.get(k):
                errs.append(f"{where}: missing/empty {k}")
        if not n.get("branches"):
            return
        for f in n["fields"]:
            if f not in all_fields:
                if f in nonreg and str(n.get("field_status", "")).startswith(NOT_IN_REGISTRY):
                    if resolution is not None and f not in resolution.get("fields", {}):
                        errs.append(f"{where}: non-registry field {f} has no entry in field_resolution.json")
                else:
                    errs.append(f"{where}: field {f} is not in the registry and node lacks field_status {NOT_IN_REGISTRY!r}")
        check_outcome(n.get("on_unexpected"), f"{where}.on_unexpected")
        node_fields = set(n["fields"])
        for b in n["branches"]:
            bw = f"{where}[{b.get('label')}]"
            for k in ("label", "when", "then"):
                if k not in b:
                    errs.append(f"{bw}: missing {k}")
            try:
                e = parse(b["when"])
            except (ExprError, KeyError) as ex:
                errs.append(f"{bw}: `when` does not parse: {ex}")
                continue
            extra = e.fields() - node_fields
            if extra:
                errs.append(f"{bw}: `when` uses fields not in node.fields: {sorted(extra)}")
            _check_literals(e, node_fields, bw, nonreg, errs)
            if "outcome" in b["then"]:
                check_outcome(b["then"], bw)
            else:
                walk(b["then"])
        # coverage warning for single select/toggle nodes
        if len(n["fields"]) == 1 and n["fields"][0] in all_fields:
            f = n["fields"][0]
            kind = registry.meta(f)["type"]["kind"]
            if kind in ("select", "toggle"):
                opts = registry.select_options(f) if kind == "select" else [True, False]
                lits = {l for fld, _, l in (x for b in n["branches"] for x in parse(b["when"]).literals()) if fld == f}
                miss = [o for o in (opts or []) if o not in lits and str(o) not in {str(l) for l in lits}]
                if miss:
                    warns.append(f"{where}: options not covered by a branch (go to on_unexpected): {miss}")

    for t in trees:
        walk(t)
    for ov in data.get("overlay_rules", []):
        check_outcome({"outcome": ov.get("outcome")}, f"{name}.overlay[{ov.get('id')}]")
        try:
            oe = parse(ov["when"])
            for f in oe.fields():
                if f not in all_fields and f not in nonreg:
                    errs.append(f"{name}.overlay[{ov['id']}]: unknown field {f}")
            _check_literals(oe, set(), f"{name}.overlay[{ov['id']}]", nonreg, errs)
        except (ExprError, KeyError) as ex:
            errs.append(f"{name}.overlay: bad `when`: {ex}")
    for oid in sorted(set(outcomes) - used):
        warns.append(f"{name}: outcome {oid} is never used")
    return errs, warns


def lint_all(directory: Path = PROTOCOLS_DIR, resolution: Optional[dict[str, Any]] = None) -> tuple[list[str], list[str]]:
    errs, warns = lint_manifest(directory), []
    for p in sorted(directory.glob("*.json")):
        if p.name == "manifest.json":
            continue
        e, w = lint_protocol(json.loads(p.read_text()), resolution)
        errs += e
        warns += w
    return errs, warns


def _load_resolution() -> Optional[dict[str, Any]]:
    p = PROTOCOLS_DIR.parent / "shared" / "field_resolution.json"
    return json.loads(p.read_text()) if p.exists() else None


if __name__ == "__main__":
    errors, warnings = lint_all(resolution=_load_resolution())
    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("ERROR:", e)
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors else 0)
