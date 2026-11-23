"""Unified CLI entrypoint for Computer Use, Portal Auditing, Drive Sync, and Zapier Dispatch."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys

from .computer_use.gemini_agent import GeminiComputerUseAgent
from .computer_use.safety import SafetyPolicy
from .computer_use.x11_controller import X11VirtualDesktop
from .config import get_settings
from .integrations.zapier_bridge import ZapierBridge
from .workflows.drive_legal_sync import sync_pinned_drive_resources
from .workflows.portals_auditor import audit_ecosystem_portals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drtapia-cu",
        description="CLI de Computer Use y Automatización Multi-Canal (drtvceo-design)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Mostrar capacidades instaladas del sistema y conectores")

    p_audit = sub.add_parser("audit-portals", help="Auditar los 12 portales UniversoLife y WordPress")
    p_audit.add_argument("--screenshots", action="store_true", help="Capturar screenshots reales con Chrome 158")

    sub.add_parser("sync-drive", help="Sincronizar e indexar recursos fijados en Google Drive (solo lectura)")

    p_mission = sub.add_parser("run-mission", help="Ejecutar una misión de Computer Use sobre una URL")
    p_mission.add_argument("--url", required=True, help="URL inicial")
    p_mission.add_argument("--goal", required=True, help="Objetivo en lenguaje natural")
    p_mission.add_argument("--allow-writes", action="store_true", help="Confirmar explícitamente escrituras")

    p_zap = sub.add_parser("zapier-test", help="Registrar/probar evento en el puente Zapier (dry-run seguro)")
    p_zap.add_argument("--event", default="system_verification", help="Tipo de evento")

    return parser


async def _async_main(args: argparse.Namespace) -> int:
    settings = get_settings()

    if args.command == "status":
        payload = {
            "gemini_model": settings.gemini_model,
            "gemini_api_key_present": bool(settings.gemini_api_key),
            "binaries": {
                **X11VirtualDesktop.capabilities(),
                "gh": shutil.which("gh"),
                "gdrive": shutil.which("gdrive"),
            },
            "output_dir": str(settings.output_dir),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.command == "audit-portals":
        report = await audit_ecosystem_portals(capture_screenshots=args.screenshots, settings=settings)
        print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
        return 0

    if args.command == "sync-drive":
        summary = sync_pinned_drive_resources(settings=settings)
        print(json.dumps(summary.model_dump(), indent=2, ensure_ascii=False))
        return 0

    if args.command == "run-mission":
        policy = SafetyPolicy(allow_writes=args.allow_writes, allow_localhost=True)
        agent = GeminiComputerUseAgent(settings=settings, safety_policy=policy)
        report = await agent.run_autonomous_mission(goal=args.goal, start_url=args.url)
        print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
        return 0 if report.status in {"completed", "waiting_for_human"} else 1

    if args.command == "zapier-test":
        bridge = ZapierBridge(settings=settings)
        receipt = await bridge.dispatch_event(
            event_type=args.event,
            data={"message": "Prueba verificada desde drtapia-computer-use CLI"},
            dry_run=True,
        )
        print(json.dumps(receipt.model_dump(), indent=2, ensure_ascii=False))
        return 0

    return 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_async_main(args)))


if __name__ == "__main__":
    main()
