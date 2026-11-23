"""Read-only HTTP/TLS/WP-REST & Chrome Computer Use auditor for the 12 Ecosystem Portals."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from ..computer_use.browser_session import BrowserComputerSession
from ..computer_use.models import ActionType, ComputerAction
from ..computer_use.safety import SafetyGateError, SafetyPolicy
from ..config import ECOSYSTEM_PORTALS, PlatformSettings, PortalTarget, get_settings


class PortalAuditEntry(BaseModel):
    """Audit status for a single UniversoLife or WordPress portal."""

    slug: str
    name: str
    category: str
    url: str
    status: Literal["online", "captcha_or_waf", "http_error", "network_restricted"]
    http_status: int | None = None
    latency_ms: float | None = None
    title: str = ""
    wp_rest_available: bool | None = None
    has_login_form: bool = False
    screenshot_path: str | None = None
    detail: str = ""


class AuditSummaryReport(BaseModel):
    """Aggregated audit report across all configured portals."""

    generated_at: str
    total_portals: int
    online_count: int
    captcha_or_waf_count: int
    restricted_or_error_count: int
    report_path: str = ""
    entries: list[PortalAuditEntry] = Field(default_factory=list)


async def _probe_single_portal(
    client: httpx.AsyncClient,
    portal: PortalTarget,
    safety: SafetyPolicy,
) -> PortalAuditEntry:
    t0 = time.perf_counter()
    try:
        resp = await client.get(portal.health_url, follow_redirects=True)
        latency = round((time.perf_counter() - t0) * 1000.0, 1)
        html = resp.text[:50000]
        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.string.strip() if soup.title and soup.title.string else "")[:140]
        has_login = bool(soup.find("input", {"type": "password"}))

        challenge = safety.detect_human_verification(url=str(resp.url), title=title, html=html)
        if challenge:
            return PortalAuditEntry(
                slug=portal.slug,
                name=portal.name,
                category=portal.category,
                url=portal.public_url,
                status="captcha_or_waf",
                http_status=resp.status_code,
                latency_ms=latency,
                title=title,
                has_login_form=has_login,
                detail=challenge,
            )

        wp_rest_ok: bool | None = None
        if portal.wp_rest_url:
            try:
                wp_resp = await client.get(portal.wp_rest_url, follow_redirects=True)
                wp_rest_ok = wp_resp.status_code == 200 and "namespaces" in wp_resp.text[:2000]
            except Exception:
                wp_rest_ok = False

        is_ok = 200 <= resp.status_code < 400
        return PortalAuditEntry(
            slug=portal.slug,
            name=portal.name,
            category=portal.category,
            url=portal.public_url,
            status="online" if is_ok else "http_error",
            http_status=resp.status_code,
            latency_ms=latency,
            title=title,
            wp_rest_available=wp_rest_ok,
            has_login_form=has_login,
            detail=f"HTTP {resp.status_code} ({latency} ms)",
        )
    except Exception as exc:
        latency = round((time.perf_counter() - t0) * 1000.0, 1)
        return PortalAuditEntry(
            slug=portal.slug,
            name=portal.name,
            category=portal.category,
            url=portal.public_url,
            status="network_restricted",
            latency_ms=latency,
            detail=f"No accesible desde red actual del entorno ({type(exc).__name__}): {str(exc)[:140]}",
        )


async def audit_ecosystem_portals(
    *,
    portals: list[PortalTarget] | None = None,
    capture_screenshots: bool = False,
    max_screenshots: int = 4,
    settings: PlatformSettings | None = None,
) -> AuditSummaryReport:
    """Audit all ecosystem portals concurrently and optionally capture Chrome 158 screenshots."""
    cfg = settings or get_settings()
    targets = portals or ECOSYSTEM_PORTALS
    safety = SafetyPolicy(allow_writes=False, allow_localhost=True)
    audit_dir = cfg.output_dir / "portal_audits"
    audit_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36 DrTapiaAuditor/1.0"
        )
    }
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        entries = list(await asyncio.gather(*(_probe_single_portal(client, p, safety) for p in targets)))

    if capture_screenshots:
        online_entries = [e for e in entries if e.status == "online"][:max_screenshots]
        if online_entries:
            shots_dir = audit_dir / "screenshots"
            async with BrowserComputerSession(
                settings=cfg,
                safety_policy=safety,
                artifacts_dir=shots_dir,
            ) as session:
                for entry in online_entries:
                    try:
                        step = await session.execute_action(
                            ComputerAction(action=ActionType.GOTO, url=entry.url, reasoning=f"Captura {entry.slug}")
                        )
                        if step.screenshot_after:
                            named_shot = shots_dir / f"{entry.slug}.png"
                            Path(step.screenshot_after).replace(named_shot)
                            entry.screenshot_path = str(named_shot)
                    except SafetyGateError as gate_err:
                        entry.status = "captcha_or_waf"
                        entry.detail = str(gate_err)
                    except Exception as shot_err:
                        entry.detail += f" | Aviso captura: {shot_err}"

    online_count = sum(1 for e in entries if e.status == "online")
    waf_count = sum(1 for e in entries if e.status == "captcha_or_waf")
    other_count = len(entries) - online_count - waf_count

    report_path = audit_dir / "latest_portal_audit.json"
    summary = AuditSummaryReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_portals=len(entries),
        online_count=online_count,
        captcha_or_waf_count=waf_count,
        restricted_or_error_count=other_count,
        report_path=str(report_path),
        entries=entries,
    )
    report_path.write_text(json.dumps(summary.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
