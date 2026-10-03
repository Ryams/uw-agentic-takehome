"""Loads field_registry.json and exposes field metadata + validation helpers.

The registry is the contract: every generated lead must validate against it.
Keep this module dependency-light so both services can import it.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

# field_registry.json lives next to this module (copied from the prompt folder).
REGISTRY_PATH = Path(__file__).with_name("field_registry.json")


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    """Return the parsed field_registry.json (cached)."""
    with REGISTRY_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def fields() -> dict[str, dict[str, Any]]:
    """Return the `fields` block: field_name -> metadata."""
    return load_registry()["fields"]


def field_names() -> list[str]:
    return list(fields().keys())


def meta(field_name: str) -> dict[str, Any]:
    return fields()[field_name]


# --- convenience predicates over the registry metadata --------------------


def is_producer_editable(field_name: str) -> bool:
    """True = producer/applicant can supply it (emailable)."""
    return bool(meta(field_name).get("editableByProducer", False))


def is_system_owned(field_name: str) -> bool:
    """True = system-owned; must be auto-fetched/derived, never emailed."""
    return not is_producer_editable(field_name)


def required_level(field_name: str) -> str:
    """One of: always | conditional | bind_only | no."""
    return meta(field_name).get("required", "no")


def select_options(field_name: str) -> list[str] | None:
    t = meta(field_name).get("type", {})
    if t.get("kind") == "select":
        return list(t.get("options", []))
    return None


def derived_from(field_name: str) -> str | None:
    """The upstream field this one is derived from, if any."""
    return meta(field_name).get("derivedFrom")


def derived_map() -> dict[str, str]:
    """derived_field -> source_field (e.g. roof_classification -> roof_material)."""
    return {f: m["derivedFrom"] for f, m in fields().items() if "derivedFrom" in m}


# --- validation -----------------------------------------------------------


def validate_value(field_name: str, value: Any) -> bool:
    """Validate a single (non-null) value against its registry type.

    `None` is always allowed (it means "missing"). Returns True if valid.
    """
    if value is None:
        return True
    kind = meta(field_name).get("type", {}).get("kind")

    if kind == "select":
        return value in (select_options(field_name) or [])
    if kind == "toggle":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "decimal":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    # address / text / email / tel / date are free-form strings here.
    return isinstance(value, str)


def validate_lead_fields(lead_fields: dict[str, Any]) -> list[str]:
    """Return a list of human-readable validation errors (empty = valid)."""
    errors: list[str] = []
    known = set(field_names())
    for name, value in lead_fields.items():
        if name not in known:
            errors.append(f"unknown field: {name}")
            continue
        if not validate_value(name, value):
            errors.append(f"invalid value for {name!r}: {value!r}")
    return errors
