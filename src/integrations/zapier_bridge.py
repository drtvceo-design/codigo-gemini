"""Zapier MCP Lifecycle Guard & Async Catch-Webhook Dispatcher.

Implements the official Zapier MCP safety rules:
1. Reads (search, find, get, list, lookup) are allowed directly.
2. Writes (send, create, update, add, delete, remove) require explicit human confirmation.
3. Duplicate detection: prefers native connected plugins ('github', 'gdrive') over Zapier equivalents.
4. Supports async HTTP Catch Hook dispatch with dry-run default and local JSONL audit outbox.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from ..computer_use.safety import WriteConfirmationRequiredError
from ..config import PlatformSettings, get_settings

READ_PREFIXES: tuple[str, ...] = ("search", "find", "get", "list", "lookup", "fetch", "read")
WRITE_PREFIXES: tuple[str, ...] = ("send", "create", "update", "add", "delete", "remove", "post", "publish")

# Apps already served by native connected plugins in this workspace
NATIVE_CONNECTED_APPS: dict[str, str] = {
    "github": "Native 'github' plugin CLI (/opt/antigravity/bin/gh)",
    "google_drive": "Native 'gdrive' plugin CLI (/opt/antigravity/bin/gdrive)",
    "gdrive": "Native 'gdrive' plugin CLI (/opt/antigravity/bin/gdrive)",
}


class ZapierActionPlan(BaseModel):
    """Describes an intended Zapier MCP or Webhook action before execution."""

    app: str
    action_name: str
    category: Literal["read", "write"]
    payload: dict[str, Any] = Field(default_factory=dict)
    prefer_native_plugin: str | None = None
    requires_confirmation: bool = False


class ZapierDispatchReceipt(BaseModel):
    """Audit receipt recorded for every Zapier webhook or staged MCP event."""

    event_id: str
    event_type: str
    timestamp: str
    dry_run: bool
    delivered: bool
    status_code: int | None = None
    payload_sha256: str
    outbox_path: str
    note: str = ""


class ZapierLifecycleGuard:
    """Enforces Zapier MCP read/write classification and native-server deduplication."""

    @staticmethod
    def classify_action(action_name: str) -> Literal["read", "write"]:
        lower = action_name.strip().lower()
        if "read_action" in lower:
            return "read"
        if "write_action" in lower:
            return "write"
        tokens = lower.replace("-", "_").split("_")
        for tok in tokens:
            if tok in WRITE_PREFIXES:
                return "write"
        for tok in tokens:
            if tok in READ_PREFIXES:
                return "read"
        # Default conservatively to write when ambiguous
        return "write"

    @classmethod
    def evaluate(
        cls,
        *,
        app: str,
        action_name: str,
        payload: dict[str, Any] | None = None,
        user_confirmed_write: bool = False,
    ) -> ZapierActionPlan:
        norm_app = app.strip().lower().replace(" ", "_")
        category = cls.classify_action(action_name)
        native_hint = NATIVE_CONNECTED_APPS.get(norm_app)
        requires_conf = category == "write"

        if requires_conf and not user_confirmed_write:
            raise WriteConfirmationRequiredError(
                f"Zapier acción de escritura '{app}:{action_name}' requiere confirmación explícita del usuario "
                f"mostrando los campos exactos: {json.dumps(payload or {}, ensure_ascii=False)[:300]}"
            )

        return ZapierActionPlan(
            app=norm_app,
            action_name=action_name,
            category=category,
            payload=payload or {},
            prefer_native_plugin=native_hint,
            requires_confirmation=requires_conf,
        )


class ZapierBridge:
    """Dispatches structured automation events to Zapier Catch Hooks and logs an auditable outbox."""

    def __init__(self, *, settings: PlatformSettings | None = None, outbox_file: Path | None = None) -> None:
        self.settings = settings or get_settings()
        self.outbox_file = outbox_file or (self.settings.output_dir / "zapier_outbox.jsonl")
        self.outbox_file.parent.mkdir(parents=True, exist_ok=True)

    async def dispatch_event(
        self,
        *,
        event_type: str,
        data: dict[str, Any],
        dry_run: bool | None = None,
        user_confirmed: bool = False,
    ) -> ZapierDispatchReceipt:
        """Stage or send an event payload to a Zapier Catch Hook URL."""
        effective_dry_run = self.settings.zapier_dry_run if dry_run is None else dry_run

        if not effective_dry_run and not user_confirmed:
            raise WriteConfirmationRequiredError(
                f"Envío en vivo a Zapier para '{event_type}' bloqueado hasta contar con user_confirmed=True."
            )

        event_id = f"zap_{uuid.uuid4().hex[:12]}"
        ts = datetime.now(timezone.utc).isoformat()
        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": ts,
            "source": "drtapia-computer-use",
            "data": data,
        }
        serialized = json.dumps(envelope, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        delivered = False
        status_code: int | None = None
        note = ""

        if effective_dry_run or not self.settings.zapier_webhook_url:
            note = (
                "Evento registrado en outbox local (modo dry-run activo o ZAPIER_WEBHOOK_URL no configurado)."
                if effective_dry_run
                else "ZAPIER_WEBHOOK_URL vacío; evento encolado en outbox local listo para reenvío."
            )
        else:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    self.settings.zapier_webhook_url,
                    json=envelope,
                    headers={"X-DrTapia-Event": event_type, "X-DrTapia-Signature-SHA256": digest},
                )
                status_code = resp.status_code
                delivered = 200 <= resp.status_code < 300
                note = f"Despachado a Zapier Catch Hook (HTTP {resp.status_code})."

        record = {**envelope, "dry_run": effective_dry_run, "delivered": delivered, "sha256": digest, "note": note}
        with self.outbox_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        return ZapierDispatchReceipt(
            event_id=event_id,
            event_type=event_type,
            timestamp=ts,
            dry_run=effective_dry_run,
            delivered=delivered,
            status_code=status_code,
            payload_sha256=digest,
            outbox_path=str(self.outbox_file),
            note=note,
        )

    def read_outbox(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return the most recent staged/dispatched Zapier events."""
        if not self.outbox_file.exists():
            return []
        lines = [ln for ln in self.outbox_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return [json.loads(ln) for ln in lines[-limit:]]
