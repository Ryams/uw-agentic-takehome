"""Mailbox access: the local mock email service over HTTP, plus an in-memory twin for tests/offline use."""

from __future__ import annotations

from typing import Any, Optional, Protocol

import httpx


class Mailbox(Protocol):
    def send(self, lead_id: str, to: str, subject: str, body: str, metadata: dict[str, Any],
             sender: str = "underwriting@stand.example") -> int: ...
    def list_for_lead(self, lead_id: str) -> list[dict[str, Any]]: ...


class HttpMailbox:
    def __init__(self, base_url: str, client: Optional[httpx.Client] = None):
        self.base, self.c = base_url.rstrip("/"), client or httpx.Client(timeout=15)

    def send(self, lead_id, to, subject, body, metadata, sender="underwriting@stand.example") -> int:
        r = self.c.post(f"{self.base}/emails", json={"lead_id": lead_id, "to": to, "from": sender,
                                                     "subject": subject, "body": body, "metadata": metadata})
        r.raise_for_status()
        return r.json()["id"]

    def list_for_lead(self, lead_id) -> list[dict[str, Any]]:
        r = self.c.get(f"{self.base}/leads/{lead_id}/emails")
        r.raise_for_status()
        return r.json()


class InMemoryMailbox:
    def __init__(self) -> None:
        self.emails: list[dict[str, Any]] = []

    def send(self, lead_id, to, subject, body, metadata, sender="underwriting@stand.example") -> int:
        self.emails.append({"id": len(self.emails) + 1, "lead_id": lead_id, "to": to, "from": sender,
                            "subject": subject, "body": body, "metadata": metadata})
        return len(self.emails)

    def list_for_lead(self, lead_id) -> list[dict[str, Any]]:
        return [e for e in self.emails if e["lead_id"] == lead_id]
