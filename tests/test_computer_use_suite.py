"""End-to-end automated tests for Computer Use (Chrome + X11), Safety Gate, Zapier Bridge, and FastAPI."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from src.computer_use.browser_session import BrowserComputerSession
from src.computer_use.gemini_agent import GeminiComputerUseAgent
from src.computer_use.models import ActionType, ComputerAction
from src.computer_use.safety import SafetyGateError, SafetyPolicy, WriteConfirmationRequiredError
from src.computer_use.x11_controller import X11VirtualDesktop
from src.config import PlatformSettings
from src.integrations.zapier_bridge import ZapierBridge, ZapierLifecycleGuard
from src.server.app import app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def live_server_url() -> str:
    """Run the FastAPI app on a real local port in a background thread for Chrome Playwright E2E tests."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=3)


def test_safety_policy_url_and_write_guards() -> None:
    policy = SafetyPolicy(allow_writes=False, allow_localhost=True)
    policy.validate_url("http://127.0.0.1:8080/sandbox/form")
    policy.validate_url("https://info.universolife.com/")

    # Block cloud metadata SSRF and file:// URLs
    with pytest.raises(SafetyGateError):
        policy.validate_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(SafetyGateError):
        policy.validate_url("file:///etc/passwd")

    # Block unconfirmed write actions
    write_action = ComputerAction(
        action=ActionType.CLICK_SELECTOR,
        selector="#publish-post",
        is_write_operation=True,
        reasoning="Publicar entrada en WordPress",
    )
    with pytest.raises(WriteConfirmationRequiredError):
        policy.validate_action(write_action)

    # Allow when user explicitly confirms writes
    confirmed_policy = SafetyPolicy(allow_writes=True)
    confirmed_policy.validate_action(write_action)


def test_safety_policy_captcha_detection() -> None:
    policy = SafetyPolicy()
    turnstile_reason = policy.detect_human_verification(
        url="https://example.com/login",
        title="Just a moment...",
        html='<div class="cf-turnstile" data-sitekey="abc"></div>',
    )
    assert turnstile_reason is not None

    recaptcha_reason = policy.detect_human_verification(
        url="https://example.com/form",
        title="Portal",
        html='<script src="https://www.google.com/recaptcha/api.js"></script>',
    )
    assert recaptcha_reason is not None

    clean_reason = policy.detect_human_verification(
        url="https://info.universolife.com/",
        title="UniversoLife Hub",
        html="<html><body><h1>Bienvenido</h1></body></html>",
    )
    assert clean_reason is None


@pytest.mark.asyncio
async def test_browser_computer_use_e2e_playbook(live_server_url: str, tmp_path: Path) -> None:
    """Verify real Chrome launch, Set-of-Marks visual tagging, form typing, button click, and DOM extraction."""
    settings = PlatformSettings(output_dir=tmp_path)
    policy = SafetyPolicy(allow_writes=False, allow_localhost=True)
    agent = GeminiComputerUseAgent(settings=settings, safety_policy=policy)

    actions = [
        ComputerAction(action=ActionType.GOTO, url=f"{live_server_url}/sandbox/form"),
        ComputerAction(
            action=ActionType.TYPE_TEXT,
            selector="#expediente",
            text="10140091",
            reasoning="Ingresar NUREJ de prueba CNS",
        ),
        ComputerAction(
            action=ActionType.CLICK_SELECTOR,
            selector="#btn-consultar",
            reasoning="Ejecutar consulta interna en el laboratorio",
        ),
        ComputerAction(
            action=ActionType.EXTRACT_DOM,
            selector="[data-testid='resultado-consulta']",
            reasoning="Leer estado resultante del DOM",
        ),
        ComputerAction(
            action=ActionType.FINISH,
            reasoning="Consulta verificada en el laboratorio local.",
        ),
    ]

    report = await agent.run_playbook(goal="Probar consulta NUREJ 10140091", actions=actions)
    assert report.status == "completed"
    assert len(report.extracted_artifacts) == 1
    extracted = report.extracted_artifacts[0]["data"]
    assert any("10140091" in item and "ACTIVO" in item for item in extracted)

    # Also verify Set-of-Marks screenshot generation directly
    async with BrowserComputerSession(settings=settings, safety_policy=policy, artifacts_dir=tmp_path / "som") as sess:
        await sess.execute_action(ComputerAction(action=ActionType.GOTO, url=f"{live_server_url}/sandbox/form"))
        obs = await sess.observe(annotate=True, include_b64=True)
        assert len(obs.interactive_elements) >= 3
        assert obs.annotated_screenshot_path is not None
        assert Path(obs.annotated_screenshot_path).exists()
        assert obs.screenshot_b64 is not None


@pytest.mark.asyncio
async def test_browser_halts_immediately_on_captcha_page(live_server_url: str, tmp_path: Path) -> None:
    """Ensure the agent stops immediately and reports 'halted_by_safety_gate' if a CAPTCHA page loads."""
    settings = PlatformSettings(output_dir=tmp_path)
    agent = GeminiComputerUseAgent(settings=settings, safety_policy=SafetyPolicy(allow_localhost=True))

    report = await agent.run_playbook(
        goal="Abrir página protegida por Turnstile",
        actions=[ComputerAction(action=ActionType.GOTO, url=f"{live_server_url}/sandbox/captcha")],
    )
    assert report.status == "halted_by_safety_gate"
    assert report.halted_reason is not None


def test_x11_virtual_desktop_mouse_and_screenshot(tmp_path: Path) -> None:
    """Verify Xvfb virtual display, xdotool mouse positioning, and scrot screenshot capture."""
    with X11VirtualDesktop(display=":98", width=1280, height=800, output_dir=tmp_path) as desktop:
        assert desktop.is_display_ready()
        desktop.move_mouse(320, 240)
        coords = desktop.get_mouse_location()
        assert coords.get("x") == 320
        assert coords.get("y") == 240

        shot = desktop.capture_screenshot("x11_test.png")
        assert shot.exists()
        assert shot.stat().st_size > 100


@pytest.mark.asyncio
async def test_zapier_lifecycle_and_dry_run_outbox(tmp_path: Path) -> None:
    # Reads are free; native plugin deduplication warns when using GitHub or Google Drive
    read_plan = ZapierLifecycleGuard.evaluate(app="github", action_name="find_pull_request")
    assert read_plan.category == "read"
    assert read_plan.prefer_native_plugin is not None

    # Writes require explicit confirmation
    with pytest.raises(WriteConfirmationRequiredError):
        ZapierLifecycleGuard.evaluate(
            app="slack",
            action_name="send_channel_message",
            payload={"channel": "#general", "text": "Hola"},
            user_confirmed_write=False,
        )

    confirmed_plan = ZapierLifecycleGuard.evaluate(
        app="slack",
        action_name="send_channel_message",
        payload={"channel": "#general", "text": "Hola"},
        user_confirmed_write=True,
    )
    assert confirmed_plan.category == "write"

    # Dry-run outbox logs SHA-256 receipt cleanly
    settings = PlatformSettings(output_dir=tmp_path)
    bridge = ZapierBridge(settings=settings)
    receipt = await bridge.dispatch_event(
        event_type="portal_audit_complete",
        data={"online": 12},
        dry_run=True,
    )
    assert receipt.dry_run is True
    assert len(receipt.payload_sha256) == 64
    events = bridge.read_outbox()
    assert len(events) == 1
    assert events[0]["event_type"] == "portal_audit_complete"


def test_fastapi_control_center_endpoints() -> None:
    client = TestClient(app)
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    r_caps = client.get("/api/system/capabilities")
    assert r_caps.status_code == 200
    assert len(r_caps.json()["portals"]) == 12

    r_ui = client.get("/")
    assert r_ui.status_code == 200
    assert "Centro de Mando" in r_ui.text
