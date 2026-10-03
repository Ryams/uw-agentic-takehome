"""Runtime settings. Reads a gitignored .env (or real env vars); never hardcode keys."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "sim-harness"
PROTOCOLS_DIR = HARNESS / "protocols"

# The harness's `shared` package (registry, schema) is reused as-is.
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    anthropic_model: str
    leadgen_url: str
    mailbox_url: str
    vendors_url: str

    @property
    def anthropic_api_key(self) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key "
                "(or export it in your shell). The key is never committed."
            )
        return key


def get_settings() -> Settings:
    return Settings(
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        leadgen_url=os.environ.get("LEADGEN_URL", "http://localhost:8081").rstrip("/"),
        mailbox_url=os.environ.get("MAILBOX_URL", "http://localhost:8025").rstrip("/"),
        vendors_url=os.environ.get("VENDORS_URL", "http://localhost:8082").rstrip("/"),
    )
