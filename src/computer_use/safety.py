"""Mandatory safety guardrails for Computer Use and external automations.

Enforces:
1. Immediate halt on CAPTCHA / Cloudflare Turnstile / human verification gates (never bypass).
2. Explicit confirmation requirement for external write operations.
3. URL scheme and cloud-metadata SSRF protection.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

from .models import ActionType, ComputerAction


class SafetyGateError(RuntimeError):
    """Raised when a CAPTCHA, anti-bot gate, or blocked URL is encountered."""


class WriteConfirmationRequiredError(RuntimeError):
    """Raised when an external write action is attempted without explicit user confirmation."""


CAPTCHA_DOM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"class=[\"'][^\"']*(?:g-recaptcha|h-captcha|cf-turnstile|altcha)[^\"']*[\"']", re.IGNORECASE),
    re.compile(r"data-sitekey=[\"'][^\"']+[\"']", re.IGNORECASE),
    re.compile(r"challenges\.cloudflare\.com/turnstile", re.IGNORECASE),
    re.compile(r"google\.com/recaptcha/api", re.IGNORECASE),
    re.compile(r"js\.hcaptcha\.com", re.IGNORECASE),
    re.compile(r"verify\s+you\s+are\s+human", re.IGNORECASE),
    re.compile(r"verifica\s+que\s+eres\s+humano", re.IGNORECASE),
    re.compile(r"checking\s+if\s+the\s+site\s+connection\s+is\s+secure", re.IGNORECASE),
)

CAPTCHA_TITLE_KEYWORDS: tuple[str, ...] = (
    "just a moment...",
    "attention required! | cloudflare",
    "verify you are human",
    "un momento...",
    "security check",
)

WRITE_KEYWORDS: tuple[str, ...] = (
    "publish",
    "publicar",
    "delete",
    "eliminar",
    "borrar",
    "enviar",
    "send",
    "transfer",
    "pay",
    "pagar",
    "checkout",
)


class SafetyPolicy:
    """Configurable safety policy enforced on every Computer Use step."""

    def __init__(
        self,
        *,
        allow_writes: bool = False,
        allow_localhost: bool = True,
        allowed_domains: set[str] | None = None,
    ) -> None:
        self.allow_writes = allow_writes
        self.allow_localhost = allow_localhost
        self.allowed_domains = {d.lower() for d in allowed_domains} if allowed_domains else None

    def validate_url(self, url: str) -> None:
        """Ensure URL uses http/https and never targets cloud metadata endpoints."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise SafetyGateError(f"Esquema de URL bloqueado por política de seguridad: '{parsed.scheme}'")

        host = (parsed.hostname or "").lower()
        if not host:
            raise SafetyGateError(f"URL inválida sin host: '{url}'")

        # Always block cloud instance metadata IPs/hosts
        if host in {"metadata.google.internal", "169.254.169.254", "metadata"}:
            raise SafetyGateError(f"Acceso bloqueado a endpoint interno de metadatos: '{host}'")

        is_local = host in {"localhost", "127.0.0.1", "::1"}
        if is_local and not self.allow_localhost:
            raise SafetyGateError("Acceso a localhost deshabilitado en esta política.")

        if not is_local:
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_link_local or ip.is_loopback or ip.is_private:
                    raise SafetyGateError(f"Acceso bloqueado a IP privada/interna: '{host}'")
            except ValueError:
                pass  # Regular domain name

        if self.allowed_domains is not None and not is_local:
            if not any(host == dom or host.endswith(f".{dom}") for dom in self.allowed_domains):
                raise SafetyGateError(f"Dominio '{host}' fuera de la lista permitida para esta misión.")

    def detect_human_verification(self, *, url: str, title: str, html: str) -> str | None:
        """Return a descriptive halt reason if the page exhibits a CAPTCHA or anti-bot gate."""
        lower_title = (title or "").strip().lower()
        for kw in CAPTCHA_TITLE_KEYWORDS:
            if kw in lower_title:
                return f"Reto anti-bot detectado en título ('{title}') en {url}. Se requiere intervención manual."

        snippet = html[:60000] if html else ""
        for pattern in CAPTCHA_DOM_PATTERNS:
            match = pattern.search(snippet)
            if match:
                return (
                    f"Widget de verificación humana/CAPTCHA detectado ({match.group(0)[:60]}) en {url}. "
                    "Ejecución detenida inmediatamente conforme a la política anti-evasión."
                )
        return None

    def validate_action(self, action: ComputerAction, target_label: str = "") -> None:
        """Validate URL navigation and write-confirmation rules before executing an action."""
        if action.action == ActionType.GOTO and action.url:
            self.validate_url(action.url)

        if self.allow_writes:
            return

        if action.is_write_operation:
            raise WriteConfirmationRequiredError(
                f"La acción '{action.action.value}' está marcada como escritura ('{action.reasoning}'). "
                "Se requiere confirmación explícita del usuario (allow_writes=True)."
            )

        combined_label = f"{action.selector or ''} {target_label}".lower()
        if action.action in {ActionType.CLICK, ActionType.CLICK_MARK, ActionType.CLICK_SELECTOR}:
            for kw in WRITE_KEYWORDS:
                if re.search(rf"\b{re.escape(kw)}\b", combined_label):
                    raise WriteConfirmationRequiredError(
                        f"Clic bloqueado preventivamente sobre control sensible ('{target_label or action.selector}'). "
                        "Confirma la escritura para continuar."
                    )
