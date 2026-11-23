# ⚡ Plataforma de Computer Use & Automatización Multi-Canal (`codigo-gemini`)

Suite modular en Python 3.12 para **Computer Use (uso agéntico de navegador Chrome 158 y escritorio virtual X11)**, auditoría automatizada de los **12 portales UniversoLife / WordPress**, sincronización documental en solo-lectura con **Google Drive** y puente dual con **Zapier MCP / Webhooks**.

## 🏗️ Arquitectura

| Módulo | Responsabilidad |
| :--- | :--- |
| `src/computer_use/browser_session.py` | Sesión asíncrona `Playwright` + `Google Chrome`, viewport `1280×800`, superposición visual **Set-of-Marks (`#1..#N`)** con `Pillow`, ejecución de clics/teclado y extracción limpia del DOM. |
| `src/computer_use/x11_controller.py` | Controlador de escritorio virtual Linux X11 (`Xvfb`, `xdpyinfo`, `xdotool`, `scrot`) para automatización GUI nativa fuera del navegador. |
| `src/computer_use/safety.py` | Cortafuegos obligatorio: detención inmediata ante CAPTCHAs / Cloudflare Turnstile (`SafetyGateError`), confirmación explícita en escrituras (`WriteConfirmationRequiredError`) y bloqueo SSRF de metadatos internos. |
| `src/computer_use/gemini_agent.py` | Bucle percepción → razonamiento multimodal con `google-genai` (`gemini-2.5-flash` / `gemini-2.5-pro`) y ejecutor determinista de playbooks con bitácora JSON auditable. |
| `src/workflows/portals_auditor.py` | Auditor concurrente de disponibilidad HTTP/TLS, APIs `/wp-json/` y capturas visuales para las 4 salas de `api.universolife.com` y los 8 paneles WordPress. |
| `src/workflows/drive_legal_sync.py` | Ingesta e indexación en solo-lectura (`gdrive readonly`) de PDFs, DOCX, Google Docs y JSON jurídicos/corporativos. |
| `src/integrations/zapier_bridge.py` | Guardián de ciclo de vida **Zapier MCP** (*lecturas libres / escrituras confirmadas* + deduplicación frente a `github` y `gdrive`) y despachador asíncrono de Catch Hooks con outbox firmado SHA-256. |
| `src/server/app.py` | API REST `FastAPI` + Consola Web interactiva + entorno local de pruebas `/sandbox/form`. |

## 🚀 Inicio Rápido

```bash
# 1. Instalar dependencias (idempotente)
python3 -m pip install -r requirements.txt

# 2. Copiar plantilla de variables de entorno (nunca subir .env a Git)
cp .env.example .env

# 3. Verificar estado de herramientas e integraciones
python3 -m src.cli status

# 4. Ejecutar suite completa de pruebas automatizadas (Chrome + Xvfb + Seguridad + Zapier)
pytest tests/ -v

# 5. Auditar portales y sincronizar expedientes de Google Drive
python3 -m src.cli audit-portals --screenshots
python3 -m src.cli sync-drive

# 6. Iniciar el Centro de Mando Web (FastAPI)
uvicorn src.server.app:app --host 0.0.0.0 --port 8080
```

## 🔒 Garantías de Seguridad

- **Cero secretos en código fuente:** Toda credencial se inyecta exclusivamente por variables de entorno (`.env` ignorado por Git).
- **Política Anti-CAPTCHA estricta:** Ningún flujo intenta resolver ni evadir verificaciones humanas; el motor pausa la sesión y alerta al operador.
- **Modo `dry-run` por defecto en escrituras externas:** Ningún webhook o acción de escritura hacia terceros se dispara en vivo sin confirmación explícita (`user_confirmed=True`).
