"""Async Playwright + Google Chrome 158 Computer Use session with Set-of-Marks visual perception."""

from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from ..config import PlatformSettings, get_settings
from .models import (
    ActionType,
    BoundingBox,
    ComputerAction,
    ExecutionStepResult,
    InteractiveElement,
    ScreenObservation,
)
from .safety import SafetyGateError, SafetyPolicy

INTERACTIVE_ELEMENTS_JS = """
() => {
  const selectors = [
    'a[href]',
    'button',
    'input:not([type="hidden"])',
    'textarea',
    'select',
    '[role="button"]',
    '[role="link"]',
    '[onclick]'
  ];
  const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
  const results = [];
  let markId = 1;

  for (const el of nodes) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) continue;
    if (rect.bottom < 0 || rect.right < 0 || rect.top > window.innerHeight || rect.left > window.innerWidth) continue;

    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity || '1') === 0) continue;

    const label = (
      el.innerText ||
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      el.getAttribute('name') ||
      el.getAttribute('title') ||
      el.value ||
      ''
    ).trim().replace(/\\s+/g, ' ').slice(0, 120);

    let selector = el.tagName.toLowerCase();
    if (el.id) {
      selector = `#${CSS.escape(el.id)}`;
    } else if (el.getAttribute('name')) {
      selector = `${el.tagName.toLowerCase()}[name="${CSS.escape(el.getAttribute('name'))}"]`;
    } else if (el.getAttribute('data-testid')) {
      selector = `[data-testid="${CSS.escape(el.getAttribute('data-testid'))}"]`;
    }

    results.push({
      mark_id: markId++,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      input_type: el.getAttribute('type') || '',
      label: label,
      href: el.getAttribute('href') || '',
      selector: selector,
      bbox: {
        x: Math.max(0, rect.left),
        y: Math.max(0, rect.top),
        width: rect.width,
        height: rect.height
      }
    });
    if (results.length >= 60) break;
  }
  return results;
}
"""


class BrowserComputerSession:
    """Managed Chrome browser session for visual perception and atomic GUI/DOM actions."""

    def __init__(
        self,
        *,
        settings: PlatformSettings | None = None,
        safety_policy: SafetyPolicy | None = None,
        artifacts_dir: Path | None = None,
        headless: bool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.safety_policy = safety_policy or SafetyPolicy()
        self.headless = self.settings.headless if headless is None else headless
        self.artifacts_dir = artifacts_dir or (self.settings.output_dir / "sessions" / f"session_{int(time.time())}")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None
        self._step_counter = 0
        self._last_elements: dict[int, InteractiveElement] = {}

    async def __aenter__(self) -> BrowserComputerSession:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def start(self) -> None:
        """Launch Chrome with isolated context and configured viewport."""
        if self.page is not None:
            return

        self._playwright = await async_playwright().start()
        chrome_path = self.settings.chrome_executable_path
        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                f"--window-size={self.settings.viewport_width},{self.settings.viewport_height}",
            ],
        }
        if chrome_path and os.path.exists(chrome_path):
            launch_kwargs["executable_path"] = chrome_path

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(
            viewport={"width": self.settings.viewport_width, "height": self.settings.viewport_height},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36 DrTapiaComputerUse/1.0"
            ),
        )
        self.page = await self._context.new_page()

    async def close(self) -> None:
        """Cleanly close page, browser context, and Playwright driver."""
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self.page = None

    def _require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("BrowserComputerSession no ha sido iniciada. Llama a await session.start().")
        return self.page

    async def _check_page_safety(self) -> None:
        """Inspect current page HTML/title and halt immediately if a CAPTCHA/challenge is present."""
        page = self._require_page()
        if page.url == "about:blank":
            return
        title = await page.title()
        html = await page.content()
        halt_reason = self.safety_policy.detect_human_verification(url=page.url, title=title, html=html)
        if halt_reason:
            raise SafetyGateError(halt_reason)

    @staticmethod
    def _extract_readable_dom(html: str, max_chars: int = 3500) -> str:
        """Strip scripts/styles and return concise structured text for LLM context."""
        soup = BeautifulSoup(html, "html.parser")
        for noisy in soup(["script", "style", "noscript", "svg"]):
            noisy.decompose()
        lines = [line.strip() for line in soup.get_text(separator="\n").splitlines() if line.strip()]
        text = "\n".join(lines)
        return text[:max_chars]

    @staticmethod
    def _render_set_of_marks(png_bytes: bytes, elements: list[InteractiveElement]) -> bytes:
        """Overlay high-contrast numbered bounding boxes onto a copy of the screenshot."""
        with Image.open(io.BytesIO(png_bytes)).convert("RGBA") as base_img:
            overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            for el in elements:
                x1 = int(el.bbox.x)
                y1 = int(el.bbox.y)
                x2 = int(el.bbox.x + el.bbox.width)
                y2 = int(el.bbox.y + el.bbox.height)
                draw.rectangle([x1, y1, x2, y2], outline=(245, 158, 11, 220), width=2)

                tag_text = f"#{el.mark_id}"
                badge_w = max(22, 7 * len(tag_text) + 6)
                badge_h = 16
                bx1 = max(0, x1)
                by1 = max(0, y1 - badge_h if y1 >= badge_h else y1)
                draw.rectangle([bx1, by1, bx1 + badge_w, by1 + badge_h], fill=(17, 24, 39, 235))
                draw.text((bx1 + 4, by1 + 2), tag_text, fill=(251, 191, 36, 255))

            composited = Image.alpha_composite(base_img, overlay).convert("RGB")
            buf = io.BytesIO()
            composited.save(buf, format="PNG", optimize=True)
            return buf.getvalue()

    async def observe(self, *, annotate: bool = True, include_b64: bool = True) -> ScreenObservation:
        """Capture current viewport screenshot, interactive elements, and DOM excerpt."""
        page = self._require_page()
        await self._check_page_safety()

        self._step_counter += 1
        step = self._step_counter

        raw_png = await page.screenshot(type="png", full_page=False)
        raw_path = self.artifacts_dir / f"step_{step:03d}_raw.png"
        raw_path.write_bytes(raw_png)

        raw_elements = await page.evaluate(INTERACTIVE_ELEMENTS_JS)
        elements = [
            InteractiveElement(
                mark_id=item["mark_id"],
                tag=item["tag"],
                role=item["role"],
                input_type=item["input_type"],
                label=item["label"],
                href=item["href"],
                selector=item["selector"],
                bbox=BoundingBox(**item["bbox"]),
            )
            for item in raw_elements
        ]
        self._last_elements = {el.mark_id: el for el in elements}

        annotated_path_str: str | None = None
        target_png_for_b64 = raw_png
        if annotate and elements:
            annotated_png = self._render_set_of_marks(raw_png, elements)
            annotated_path = self.artifacts_dir / f"step_{step:03d}_som.png"
            annotated_path.write_bytes(annotated_png)
            annotated_path_str = str(annotated_path)
            target_png_for_b64 = annotated_png

        html = await page.content()
        dom_excerpt = self._extract_readable_dom(html)

        return ScreenObservation(
            step=step,
            url=page.url,
            title=await page.title(),
            viewport_width=self.settings.viewport_width,
            viewport_height=self.settings.viewport_height,
            screenshot_path=str(raw_path),
            annotated_screenshot_path=annotated_path_str,
            screenshot_b64=base64.b64encode(target_png_for_b64).decode("ascii") if include_b64 else None,
            dom_excerpt=dom_excerpt,
            interactive_elements=elements,
        )

    async def execute_action(self, action: ComputerAction) -> ExecutionStepResult:
        """Validate safety rules and execute one atomic ComputerAction."""
        page = self._require_page()
        t0 = time.perf_counter()

        target_label = ""
        if action.mark_id and action.mark_id in self._last_elements:
            target_label = self._last_elements[action.mark_id].label

        self.safety_policy.validate_action(action, target_label=target_label)

        extracted_data: Any = None
        msg = ""

        if action.action == ActionType.GOTO:
            if not action.url:
                raise ValueError("Action 'goto' requiere 'url'.")
            await page.goto(action.url, wait_until="domcontentloaded", timeout=30000)
            await self._check_page_safety()
            msg = f"Navegado exitosamente a {page.url}"

        elif action.action == ActionType.CLICK:
            if action.x is None or action.y is None:
                raise ValueError("Action 'click' requiere coordenadas (x, y).")
            await page.mouse.click(action.x, action.y)
            await page.wait_for_timeout(350)
            await self._check_page_safety()
            msg = f"Clic en coordenadas ({action.x}, {action.y})"

        elif action.action == ActionType.CLICK_MARK:
            if action.mark_id is None or action.mark_id not in self._last_elements:
                raise ValueError(f"Mark ID #{action.mark_id} no encontrado en la observación actual.")
            el = self._last_elements[action.mark_id]
            await page.mouse.click(el.bbox.center_x, el.bbox.center_y)
            await page.wait_for_timeout(350)
            await self._check_page_safety()
            msg = f"Clic en marca #{el.mark_id} ({el.tag}: '{el.label[:40]}')"

        elif action.action == ActionType.CLICK_SELECTOR:
            if not action.selector:
                raise ValueError("Action 'click_selector' requiere 'selector'.")
            await page.locator(action.selector).first.click(timeout=10000)
            await page.wait_for_timeout(350)
            await self._check_page_safety()
            msg = f"Clic en selector '{action.selector}'"

        elif action.action == ActionType.TYPE_TEXT:
            text_val = action.text or ""
            if action.mark_id and action.mark_id in self._last_elements:
                el = self._last_elements[action.mark_id]
                await page.mouse.click(el.bbox.center_x, el.bbox.center_y)
                if action.clear_before_type:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                await page.keyboard.type(text_val)
            elif action.selector:
                loc = page.locator(action.selector).first
                if action.clear_before_type:
                    await loc.fill(text_val, timeout=10000)
                else:
                    await loc.type(text_val, timeout=10000)
            else:
                await page.keyboard.type(text_val)

            if action.press_enter:
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(350)
            await self._check_page_safety()
            msg = f"Texto ingresado ({len(text_val)} caracteres)"

        elif action.action == ActionType.PRESS_KEY:
            key_name = action.key or "Enter"
            await page.keyboard.press(key_name)
            await page.wait_for_timeout(250)
            await self._check_page_safety()
            msg = f"Tecla presionada: {key_name}"

        elif action.action == ActionType.SCROLL:
            await page.mouse.wheel(0, action.delta_y)
            await page.wait_for_timeout(250)
            msg = f"Scroll vertical delta_y={action.delta_y}"

        elif action.action == ActionType.WAIT:
            await page.wait_for_timeout(max(50, min(action.wait_ms, 10000)))
            msg = f"Espera completada ({action.wait_ms} ms)"

        elif action.action == ActionType.EXTRACT_DOM:
            if action.selector:
                nodes = await page.locator(action.selector).all_inner_texts()
                extracted_data = [n.strip() for n in nodes if n.strip()]
            else:
                extracted_data = self._extract_readable_dom(await page.content(), max_chars=8000)
            msg = "Extracción estructurada del DOM completada"

        elif action.action in {ActionType.FINISH, ActionType.ASK_HUMAN}:
            msg = action.reasoning or f" Estado final: {action.action.value}"

        obs_after = await self.observe(annotate=False, include_b64=False)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        return ExecutionStepResult(
            step=obs_after.step,
            action=action,
            success=True,
            message=msg,
            extracted_data=extracted_data,
            url_after=obs_after.url,
            title_after=obs_after.title,
            screenshot_after=obs_after.screenshot_path,
            duration_ms=elapsed_ms,
        )
