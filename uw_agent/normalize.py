"""Lead normalization: coerce types and treat sentinel values as missing.

Raw leads are messy (numeric strings like "300000", "Unknown", empty strings). The
normalizer returns every registry field (absent -> None) with canonical types, plus notes
about what it changed and any values it could not make valid (those become missing and
are listed in `invalid` so the pipeline can ask rather than guess).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import uw_agent.config  # noqa: F401  (sim-harness on sys.path)
from shared import registry

SENTINELS = {"", "unknown", "n/a", "na", "null", "tbd", "-", "--", "?"}
_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


@dataclass
class Normalized:
    values: dict[str, Any]
    notes: list[dict[str, Any]] = field(default_factory=list)    # coercions / sentinels
    invalid: list[dict[str, Any]] = field(default_factory=list)  # unusable values (treated as missing)


def _coerce(name: str, raw: Any) -> tuple[Any, str]:
    """Returns (value, status): status is 'ok' | 'coerced' | 'sentinel' | 'invalid'."""
    kind = registry.meta(name)["type"]["kind"]
    if raw is None:
        return None, "ok"
    if isinstance(raw, str):
        s = raw.strip()
        if s.lower() in SENTINELS:
            return None, "sentinel"
    else:
        s = raw

    if kind == "select":
        opts = registry.select_options(name) or []
        for o in opts:
            if str(o).lower() == str(s).strip().lower():
                return o, "ok" if o == raw else "coerced"
        return None, "invalid"
    if kind == "toggle":
        if isinstance(s, bool):
            return s, "ok"
        low = str(s).strip().lower()
        if low in _TRUE or low in _FALSE:
            return low in _TRUE, "coerced"
        return None, "invalid"
    if kind in ("integer", "decimal"):
        if isinstance(s, bool):
            return None, "invalid"
        if isinstance(s, (int, float)):
            num = s
        else:
            cleaned = re.sub(r"[,$\s]", "", str(s))
            try:
                num = float(cleaned)
            except ValueError:
                return None, "invalid"
        if kind == "integer":
            if float(num) != int(num):
                return None, "invalid"
            return int(num), "ok" if isinstance(raw, int) and not isinstance(raw, bool) else "coerced"
        return float(num), "ok" if isinstance(raw, float) else "coerced"
    if kind == "date":
        try:
            date.fromisoformat(str(s))
        except ValueError:
            return None, "invalid"
        return str(s), "ok"
    # text / address / email / tel
    if not isinstance(s, str):
        return str(s), "coerced"
    return s, "ok" if s == raw else "coerced"


def normalize_lead(raw_fields: dict[str, Any]) -> Normalized:
    known = registry.field_names()
    out = Normalized(values={n: None for n in known})
    for name, raw in raw_fields.items():
        if name not in known:
            out.invalid.append({"field": name, "value": raw, "reason": "unknown field"})
            continue
        value, status = _coerce(name, raw)
        out.values[name] = value
        if status == "coerced":
            out.notes.append({"field": name, "kind": "coerced", "from": raw, "to": value})
        elif status == "sentinel":
            out.notes.append({"field": name, "kind": "sentinel_to_missing", "from": raw, "to": None})
        elif status == "invalid":
            out.invalid.append({"field": name, "value": raw, "reason": "not valid for field type"})
    return out
