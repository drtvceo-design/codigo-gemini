"""Multimodal Gemini 2.5 Computer Use Agent & Deterministic Playbook Runner."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from google.genai import types

from ..config import PlatformSettings, get_settings
from .browser_session import BrowserComputerSession
from .models import ActionType, ComputerAction, ExecutionStepResult, MissionReport, ScreenObservation
from .safety import SafetyGateError, SafetyPolicy, WriteConfirmationRequiredError

SYSTEM_PROMPT_COMPUTER_USE = """Eres el Agente de Computer Use del ecosistema del Dr. Ignacio Tapia Vargas.
Recibes en cada paso:
1. El objetivo del usuario.
2. Una captura de pantalla 1280x800 anotada con etiquetas numéricas (#1, #2, ...) sobre elementos interactivos (Set-of-Marks).
3. El índice de elementos interactivos con coordenadas y etiquetas.
4. El historial reciente de pasos ejecutados.

REGLAS ESTRICTAS:
- Devuelve ÚNICAMENTE un objeto JSON válido que cumpla el esquema ComputerAction.
- Prefiere 'click_mark' (indicando mark_id) cuando el elemento tenga una etiqueta #N visible.
- Si una acción modifica datos externos (publicar, borrar, pagar, enviar formularios a terceros), marca is_write_operation=true.
- Si detectas un CAPTCHA, Cloudflare Turnstile o solicitud de contraseña no provista, emite action='ask_human' explicando el motivo en 'reasoning'. Jamás intentes evadir controles.
- Cuando el objetivo esté cumplido, emite action='finish' con un resumen ejecutivo claro en 'reasoning'.
"""


class GeminiComputerUseAgent:
    """Executes visual web/GUI missions via Gemini 2.5 Vision or deterministic playbooks."""

    def __init__(
        self,
        *,
        settings: PlatformSettings | None = None,
        safety_policy: SafetyPolicy | None = None,
        max_steps: int = 12,
    ) -> None:
        self.settings = settings or get_settings()
        self.safety_policy = safety_policy or SafetyPolicy()
        self.max_steps = max_steps

    def _plan_with_gemini(
        self,
        *,
        goal: str,
        observation: ScreenObservation,
        history: list[ExecutionStepResult],
    ) -> ComputerAction:
        """Query Gemini 2.5 multimodal API with annotated screenshot + Set-of-Marks catalog."""
        client = genai.Client(api_key=self.settings.gemini_api_key)

        marks_text = "\n".join(
            f"#{el.mark_id} [{el.tag} {el.input_type or el.role}] label='{el.label}' href='{el.href}' "
            f"center=({el.bbox.center_x},{el.bbox.center_y})"
            for el in observation.interactive_elements[:40]
        )
        history_text = "\n".join(
            f"Paso {h.step}: {h.action.action.value} -> {h.message} (URL: {h.url_after})"
            for h in history[-6:]
        )
        prompt = (
            f"OBJETIVO: {goal}\n"
            f"URL ACTUAL: {observation.url}\n"
            f"TÍTULO: {observation.title}\n\n"
            f"HISTORIAL RECIENTE:\n{history_text or '(inicio de misión)'}\n\n"
            f"ELEMENTOS INTERACTIVOS (SET-OF-MARKS):\n{marks_text or '(ninguno detectado)'}\n\n"
            f"EXTRACTO TEXTO DOM:\n{observation.dom_excerpt[:1800]}\n\n"
            "Decide la siguiente ComputerAction en formato JSON."
        )

        contents: list[types.Part | str] = []
        if observation.screenshot_b64:
            png_bytes = base64.b64decode(observation.screenshot_b64)
            contents.append(types.Part.from_bytes(data=png_bytes, mime_type="image/png"))
        contents.append(prompt)

        response = client.models.generate_content(
            model=self.settings.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT_COMPUTER_USE,
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=ComputerAction,
            ),
        )
        raw_text = (response.text or "").strip()
        return ComputerAction.model_validate_json(raw_text)

    async def run_playbook(
        self,
        *,
        goal: str,
        actions: list[ComputerAction],
        session: BrowserComputerSession | None = None,
    ) -> MissionReport:
        """Execute a deterministic sequence of ComputerActions with full observation & safety auditing."""
        mission_id = f"mission_{uuid.uuid4().hex[:10]}"
        report = MissionReport(
            mission_id=mission_id,
            goal=goal,
            started_at=datetime.now(timezone.utc).isoformat(),
            planner_mode="playbook",
        )

        owns_session = session is None
        active_session = session or BrowserComputerSession(
            settings=self.settings,
            safety_policy=self.safety_policy,
            artifacts_dir=self.settings.output_dir / "missions" / mission_id,
        )

        try:
            if owns_session:
                await active_session.start()

            for action in actions:
                # Refresh Set-of-Marks before mark-based actions
                if action.mark_id is not None:
                    await active_session.observe(annotate=True, include_b64=False)

                step_res = await active_session.execute_action(action)
                report.steps.append(step_res)
                if step_res.extracted_data is not None:
                    report.extracted_artifacts.append(
                        {"step": step_res.step, "url": step_res.url_after, "data": step_res.extracted_data}
                    )

                if action.action == ActionType.FINISH:
                    report.status = "completed"
                    report.final_summary = action.reasoning or "Playbook ejecutado exitosamente."
                    break
                if action.action == ActionType.ASK_HUMAN:
                    report.status = "waiting_for_human"
                    report.halted_reason = action.reasoning or "Se solicitó intervención del usuario."
                    break
            else:
                report.status = "completed"
                report.final_summary = f"Playbook finalizado tras {len(report.steps)} pasos."

        except (SafetyGateError, WriteConfirmationRequiredError) as gate_err:
            report.status = "halted_by_safety_gate"
            report.halted_reason = str(gate_err)
            report.final_summary = f"Detenido de forma segura: {gate_err}"
        except Exception as exc:
            report.status = "failed"
            report.halted_reason = str(exc)
            report.final_summary = f"Error durante ejecución: {exc}"
        finally:
            report.finished_at = datetime.now(timezone.utc).isoformat()
            self._persist_report(report, active_session.artifacts_dir)
            if owns_session:
                await active_session.close()

        return report

    async def run_autonomous_mission(
        self,
        *,
        goal: str,
        start_url: str,
    ) -> MissionReport:
        """Run an autonomous perception -> Gemini 2.5 reasoning -> action mission starting at start_url."""
        mission_id = f"mission_{uuid.uuid4().hex[:10]}"
        planner_mode = "gemini" if self.settings.gemini_api_key else "heuristic_inspector"
        report = MissionReport(
            mission_id=mission_id,
            goal=goal,
            started_at=datetime.now(timezone.utc).isoformat(),
            planner_mode=planner_mode,
        )

        mission_dir = self.settings.output_dir / "missions" / mission_id
        async with BrowserComputerSession(
            settings=self.settings,
            safety_policy=self.safety_policy,
            artifacts_dir=mission_dir,
        ) as session:
            try:
                init_step = await session.execute_action(
                    ComputerAction(action=ActionType.GOTO, url=start_url, reasoning=f"Abrir URL inicial {start_url}")
                )
                report.steps.append(init_step)

                if not self.settings.gemini_api_key:
                    # Offline deterministic visual inspection + DOM extraction fallback
                    obs = await session.observe(annotate=True, include_b64=False)
                    extract_step = await session.execute_action(
                        ComputerAction(
                            action=ActionType.EXTRACT_DOM,
                            reasoning="Extraer contenido legible del DOM y mapa Set-of-Marks (modo sin GEMINI_API_KEY).",
                        )
                    )
                    report.steps.append(extract_step)
                    report.extracted_artifacts.append(
                        {
                            "url": obs.url,
                            "title": obs.title,
                            "interactive_count": len(obs.interactive_elements),
                            "annotated_screenshot": obs.annotated_screenshot_path or obs.screenshot_path,
                            "excerpt": obs.dom_excerpt[:1200],
                        }
                    )
                    report.status = "completed"
                    report.final_summary = (
                        f"Inspección visual completada en '{obs.title}' ({len(obs.interactive_elements)} controles "
                        "interactivos detectados y etiquetados). Define GEMINI_API_KEY en .env para habilitar "
                        "navegación autónoma multi-paso con Gemini 2.5."
                    )
                else:
                    for _ in range(self.max_steps):
                        obs = await session.observe(annotate=True, include_b64=True)
                        next_action = self._plan_with_gemini(goal=goal, observation=obs, history=report.steps)
                        step_res = await session.execute_action(next_action)
                        report.steps.append(step_res)
                        if step_res.extracted_data is not None:
                            report.extracted_artifacts.append(
                                {"step": step_res.step, "url": step_res.url_after, "data": step_res.extracted_data}
                            )

                        if next_action.action == ActionType.FINISH:
                            report.status = "completed"
                            report.final_summary = next_action.reasoning or "Misión completada."
                            break
                        if next_action.action == ActionType.ASK_HUMAN:
                            report.status = "waiting_for_human"
                            report.halted_reason = next_action.reasoning
                            report.final_summary = f"Esperando al usuario: {next_action.reasoning}"
                            break
                    else:
                        report.status = "max_steps_reached"
                        report.final_summary = f"Se alcanzó el límite máximo de {self.max_steps} pasos."

            except (SafetyGateError, WriteConfirmationRequiredError) as gate_err:
                report.status = "halted_by_safety_gate"
                report.halted_reason = str(gate_err)
                report.final_summary = f"Detenido de forma segura: {gate_err}"
            except Exception as exc:
                report.status = "failed"
                report.halted_reason = str(exc)
                report.final_summary = f"Fallo en misión: {exc}"
            finally:
                report.finished_at = datetime.now(timezone.utc).isoformat()
                self._persist_report(report, mission_dir)

        return report

    @staticmethod
    def _persist_report(report: MissionReport, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        trace_file = directory / "mission_report.json"
        trace_file.write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
