"""Linux X11 Virtual Desktop controller (Xvfb + xdotool + scrot + xdpyinfo)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class X11VirtualDesktop:
    """Manages an isolated Xvfb virtual framebuffer for X11 GUI Computer Use."""

    def __init__(
        self,
        *,
        display: str = ":99",
        width: int = 1280,
        height: int = 800,
        depth: int = 24,
        output_dir: Path | None = None,
    ) -> None:
        self.display = display
        self.width = width
        self.height = height
        self.depth = depth
        self.output_dir = output_dir or Path("/tmp/drtapia_x11")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._xvfb_proc: subprocess.Popen[bytes] | None = None

    @staticmethod
    def capabilities() -> dict[str, str | None]:
        """Return paths of available X11 Computer Use binaries."""
        return {
            "xvfb_run": shutil.which("xvfb-run"),
            "Xvfb": shutil.which("Xvfb"),
            "xdotool": shutil.which("xdotool"),
            "scrot": shutil.which("scrot"),
            "xdpyinfo": shutil.which("xdpyinfo"),
            "google_chrome": shutil.which("google-chrome"),
        }

    def __enter__(self) -> X11VirtualDesktop:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        return env

    def is_display_ready(self) -> bool:
        """Check whether the Xvfb display accepts X11 client connections."""
        res = subprocess.run(
            ["xdpyinfo", "-display", self.display],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return res.returncode == 0

    def start(self) -> None:
        """Start Xvfb if the target display is not already active."""
        if self.is_display_ready():
            return

        xvfb_bin = shutil.which("Xvfb")
        if not xvfb_bin:
            raise RuntimeError("Xvfb no está instalado en el sistema.")

        self._xvfb_proc = subprocess.Popen(
            [
                xvfb_bin,
                self.display,
                "-screen",
                "0",
                f"{self.width}x{self.height}x{self.depth}",
                "-ac",
                "-noreset",
                "+extension",
                "RANDR",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        for _ in range(30):
            if self.is_display_ready():
                return
            time.sleep(0.1)

        self.stop()
        raise RuntimeError(f"No se pudo inicializar el display Xvfb en {self.display}.")

    def stop(self) -> None:
        """Terminate managed Xvfb process if owned by this instance."""
        if self._xvfb_proc is not None:
            self._xvfb_proc.terminate()
            try:
                self._xvfb_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._xvfb_proc.kill()
            self._xvfb_proc = None

    def move_mouse(self, x: int, y: int) -> None:
        """Move X11 cursor to (x, y) via xdotool."""
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], env=self._env(), check=True)

    def get_mouse_location(self) -> dict[str, int]:
        """Read current X11 cursor coordinates via xdotool."""
        out = subprocess.check_output(["xdotool", "getmouselocation", "--shell"], env=self._env(), text=True)
        coords: dict[str, int] = {}
        for line in out.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if v.isdigit():
                    coords[k.lower()] = int(v)
        return coords

    def click(self, button: int = 1) -> None:
        """Send mouse click event (1=left, 2=middle, 3=right)."""
        subprocess.run(["xdotool", "click", str(button)], env=self._env(), check=True)

    def key(self, key_combo: str) -> None:
        """Send key press combination (e.g., 'Return', 'ctrl+l')."""
        subprocess.run(["xdotool", "key", key_combo], env=self._env(), check=True)

    def capture_screenshot(self, filename: str | None = None) -> Path:
        """Capture full virtual X11 root screen using scrot."""
        target = self.output_dir / (filename or f"x11_{int(time.time() * 1000)}.png")
        subprocess.run(["scrot", "--overwrite", str(target)], env=self._env(), check=True)
        return target
