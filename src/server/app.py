"""FastAPI Control Center for Computer Use, Portal Auditing, Drive Sync, and Zapier Bridge."""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..computer_use.gemini_agent import GeminiComputerUseAgent
from ..computer_use.safety import SafetyPolicy, WriteConfirmationRequiredError
from ..computer_use.x11_controller import X11VirtualDesktop
from ..config import ECOSYSTEM_PORTALS, PINNED_DRIVE_RESOURCES, get_settings
from ..integrations.zapier_bridge import ZapierBridge, ZapierLifecycleGuard
from ..workflows.drive_legal_sync import sync_pinned_drive_resources
from ..workflows.portals_auditor import audit_ecosystem_portals

app = FastAPI(
    title="Dr. Tapia Computer Use & Automation Command Center",
    version="1.0.0",
    description="API y consola interactiva para Computer Use (Chrome 158 + Xvfb + Gemini 2.5), portales, GDrive y Zapier.",
)


class MissionRequest(BaseModel):
    goal: str = Field(..., min_length=3)
    start_url: str = Field(..., min_length=8)
    allow_writes: bool = False
    max_steps: int = Field(default=8, ge=1, le=20)


class ZapierDispatchRequest(BaseModel):
    event_type: str = Field(default="automation_digest", min_length=2)
    data: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True
    user_confirmed: bool = False


class ZapierEvaluateRequest(BaseModel):
    app: str
    action_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    user_confirmed_write: bool = False


@app.get("/api/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "drtapia-computer-use",
        "gemini_key_configured": bool(settings.gemini_api_key),
        "gemini_model": settings.gemini_model,
        "zapier_dry_run": settings.zapier_dry_run,
        "portals_registered": len(ECOSYSTEM_PORTALS),
        "drive_resources_registered": len(PINNED_DRIVE_RESOURCES),
    }


@app.get("/api/system/capabilities")
async def system_capabilities() -> dict[str, Any]:
    x11_caps = X11VirtualDesktop.capabilities()
    return {
        "x11_and_browser": x11_caps,
        "plugins": {
            "gh": shutil.which("gh"),
            "gdrive": shutil.which("gdrive"),
        },
        "portals": [p.model_dump() for p in ECOSYSTEM_PORTALS],
        "drive_resources": [r.model_dump() for r in PINNED_DRIVE_RESOURCES],
    }


@app.post("/api/portals/audit")
async def api_audit_portals(capture_screenshots: bool = False) -> dict[str, Any]:
    summary = await audit_ecosystem_portals(capture_screenshots=capture_screenshots)
    return summary.model_dump()


@app.post("/api/drive/sync")
async def api_sync_drive() -> dict[str, Any]:
    summary = sync_pinned_drive_resources()
    return summary.model_dump()


@app.post("/api/computer-use/execute")
async def api_execute_mission(req: MissionRequest) -> dict[str, Any]:
    policy = SafetyPolicy(allow_writes=req.allow_writes, allow_localhost=True)
    agent = GeminiComputerUseAgent(safety_policy=policy, max_steps=req.max_steps)
    report = await agent.run_autonomous_mission(goal=req.goal, start_url=req.start_url)
    return report.model_dump()


@app.post("/api/zapier/evaluate")
async def api_zapier_evaluate(req: ZapierEvaluateRequest) -> dict[str, Any]:
    try:
        plan = ZapierLifecycleGuard.evaluate(
            app=req.app,
            action_name=req.action_name,
            payload=req.payload,
            user_confirmed_write=req.user_confirmed_write,
        )
        return plan.model_dump()
    except WriteConfirmationRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/zapier/dispatch")
async def api_zapier_dispatch(req: ZapierDispatchRequest) -> dict[str, Any]:
    bridge = ZapierBridge()
    try:
        receipt = await bridge.dispatch_event(
            event_type=req.event_type,
            data=req.data,
            dry_run=req.dry_run,
            user_confirmed=req.user_confirmed,
        )
        return receipt.model_dump()
    except WriteConfirmationRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/zapier/outbox")
async def api_zapier_outbox(limit: int = 20) -> dict[str, Any]:
    bridge = ZapierBridge()
    return {"events": bridge.read_outbox(limit=limit)}


@app.get("/sandbox/form", response_class=HTMLResponse)
async def sandbox_form() -> str:
    """Safe local testbench page for verifying Computer Use navigation, Set-of-Marks, typing, and DOM extraction."""
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <title>Laboratorio Local Computer Use · Ecosistema Dr. Tapia</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; padding: 32px; }
    .box { max-width: 640px; background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px; }
    label { display: block; margin-top: 12px; font-size: 14px; color: #cbd5e1; }
    input, select { width: 100%; padding: 10px; margin-top: 6px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: #fff; }
    button { margin-top: 18px; padding: 11px 18px; border-radius: 8px; border: none; background: #10b981; color: #052e16; font-weight: 700; cursor: pointer; }
    #resultado { margin-top: 18px; padding: 12px; border-radius: 8px; background: #064e3b; display: none; }
  </style>
</head>
<body>
  <div class="box">
    <h1> Mesa de Pruebas Computer Use</h1>
    <p>Formulario controlado de verificación para agentes Playwright + Chrome 158.</p>
    <label for="expediente">Código NUREJ / Expediente</label>
    <input id="expediente" name="expediente" type="text" placeholder="Ej. 10140091" />
    <label for="juzgado">Despacho / Portal</label>
    <select id="juzgado" name="juzgado">
      <option value="Juzgado 3ro Trabajo Sucre">Juzgado 3° de Trabajo y S.S. Sucre</option>
      <option value="UniversoLife Hub">UniversoLife Hub Central</option>
    </select>
    <button id="btn-consultar" type="button" onclick="procesar()">Consultar Estado Interno</button>
    <div id="resultado" data-testid="resultado-consulta"></div>
  </div>
  <script>
    function procesar() {
      const exp = document.getElementById('expediente').value || 'SIN-CODIGO';
      const juz = document.getElementById('juzgado').value;
      const out = document.getElementById('resultado');
      out.style.display = 'block';
      out.textContent = 'CONSULTA VERIFICADA: NUREJ ' + exp + ' en ' + juz + ' — Estado: ACTIVO';
    }
  </script>
</body>
</html>"""


@app.get("/sandbox/captcha", response_class=HTMLResponse)
async def sandbox_captcha() -> str:
    """Simulated challenge page strictly used to test that SafetyPolicy halts immediately."""
    return """<!DOCTYPE html>
<html lang="en">
<head><title>Just a moment...</title></head>
<body>
  <div class="cf-turnstile" data-sitekey="0x4AAAAAA_TEST_ONLY"></div>
  <p>Verify you are human before continuing.</p>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard_ui() -> str:
    """Interactive live Web Console for launching and inspecting automations."""
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Centro de Mando Computer Use & Automatización · Dr. Tapia</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-6 font-sans">
  <div class="max-w-6xl mx-auto space-y-6">
    <header class="flex flex-wrap items-center justify-between gap-4 bg-slate-900 border border-slate-800 rounded-2xl p-5">
      <div>
        <h1 class="text-xl font-bold text-amber-400">⚡ Centro de Mando: Computer Use, GDrive & Zapier</h1>
        <p class="text-xs text-slate-400 mt-1">Chrome 158 · Playwright Set-of-Marks · Xvfb :99 · Gemini 2.5 · Cortafuegos Anti-CAPTCHA</p>
      </div>
      <div id="health-pill" class="text-xs font-mono px-3 py-1.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-700">
        Verificando API...
      </div>
    </header>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <button onclick="triggerAction('/api/portals/audit', 'POST')" class="p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-amber-500 text-left transition cursor-pointer">
        <div class="text-sm font-semibold text-amber-300">🌐 Auditar 12 Portales</div>
        <p class="text-xs text-slate-400 mt-1">Verifica latencia, TLS y APIs WP-REST de UniversoLife y WordPress.</p>
      </button>
      <button onclick="triggerAction('/api/drive/sync', 'POST')" class="p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-emerald-500 text-left transition cursor-pointer">
        <div class="text-sm font-semibold text-emerald-300">📂 Sincronizar Expedientes Drive</div>
        <p class="text-xs text-slate-400 mt-1">Indexa en solo-lectura PDFs, DOCX y JSON de CNS Juzgado 3° / NUREJ 10140091.</p>
      </button>
      <button onclick="runSandboxMission()" class="p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-indigo-500 text-left transition cursor-pointer">
        <div class="text-sm font-semibold text-indigo-300">🖥️ Ejecutar Misión Computer Use</div>
        <p class="text-xs text-slate-400 mt-1">Lanza Chrome 158 con Set-of-Marks sobre el laboratorio local y extrae el DOM.</p>
      </button>
    </div>

    <section class="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-semibold text-slate-200">Salida Estructurada en Vivo</h2>
        <span id="run-state" class="text-xs font-mono text-slate-400">En espera</span>
      </div>
      <pre id="console-out" class="bg-slate-950 border border-slate-800 rounded-xl p-4 text-xs font-mono text-emerald-300 overflow-x-auto max-h-96">Selecciona una operación arriba para ejecutarla en vivo.</pre>
    </section>
  </div>

  <script>
    async function loadHealth() {
      const r = await fetch('/api/health');
      const d = await r.json();
      document.getElementById('health-pill').textContent =
        `ACTIVO · ${d.portals_registered} Portales · ${d.drive_resources_registered} Docs Drive · Modelo: ${d.gemini_model}`;
    }
    async function triggerAction(url, method) {
      document.getElementById('run-state').textContent = 'Ejecutando ' + url + '...';
      const r = await fetch(url, { method });
      const d = await r.json();
      document.getElementById('console-out').textContent = JSON.stringify(d, null, 2);
      document.getElementById('run-state').textContent = 'Completado (HTTP ' + r.status + ')';
    }
    async function runSandboxMission() {
      document.getElementById('run-state').textContent = 'Ejecutando Computer Use en Chrome 158...';
      const r = await fetch('/api/computer-use/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          goal: 'Inspeccionar formulario de expediente NUREJ y etiquetar controles interactivos',
          start_url: window.location.origin + '/sandbox/form',
          allow_writes: false
        })
      });
      const d = await r.json();
      document.getElementById('console-out').textContent = JSON.stringify(d, null, 2);
      document.getElementById('run-state').textContent = 'Misión finalizada: ' + d.status;
    }
    loadHealth();
  </script>
</body>
</html>"""
