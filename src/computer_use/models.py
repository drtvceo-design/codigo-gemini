"""Data models for Computer Use perception, Set-of-Marks elements, actions, and traces."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Supported atomic Computer Use operations."""

    GOTO = "goto"
    CLICK = "click"
    CLICK_MARK = "click_mark"
    CLICK_SELECTOR = "click_selector"
    TYPE_TEXT = "type_text"
    PRESS_KEY = "press_key"
    SCROLL = "scroll"
    WAIT = "wait"
    EXTRACT_DOM = "extract_dom"
    FINISH = "finish"
    ASK_HUMAN = "ask_human"


class BoundingBox(BaseModel):
    """Screen coordinates inside the viewport."""

    x: float
    y: float
    width: float
    height: float

    @property
    def center_x(self) -> int:
        return int(round(self.x + self.width / 2.0))

    @property
    def center_y(self) -> int:
        return int(round(self.y + self.height / 2.0))


class InteractiveElement(BaseModel):
    """Visible interactive DOM element tagged with a numeric Set-of-Marks ID."""

    mark_id: int
    tag: str
    role: str = ""
    input_type: str = ""
    label: str = ""
    href: str = ""
    selector: str = ""
    bbox: BoundingBox


class ComputerAction(BaseModel):
    """Structured action emitted by Gemini 2.5 Vision or a deterministic playbook."""

    action: ActionType
    url: str | None = None
    x: int | None = None
    y: int | None = None
    mark_id: int | None = None
    selector: str | None = None
    text: str | None = None
    key: str | None = None
    delta_y: int = 400
    wait_ms: int = 800
    clear_before_type: bool = True
    press_enter: bool = False
    is_write_operation: bool = False
    reasoning: str = ""


class ScreenObservation(BaseModel):
    """Snapshot of the browser/desktop state at a given step."""

    step: int
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    url: str
    title: str
    viewport_width: int
    viewport_height: int
    screenshot_path: str | None = None
    annotated_screenshot_path: str | None = None
    screenshot_b64: str | None = None
    dom_excerpt: str = ""
    interactive_elements: list[InteractiveElement] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)


class ExecutionStepResult(BaseModel):
    """Record of executing a single ComputerAction."""

    step: int
    action: ComputerAction
    success: bool
    message: str = ""
    extracted_data: Any = None
    url_after: str = ""
    title_after: str = ""
    screenshot_after: str | None = None
    duration_ms: float = 0.0


class MissionReport(BaseModel):
    """Complete auditable trace of a Computer Use mission."""

    mission_id: str
    goal: str
    started_at: str
    finished_at: str = ""
    status: str = "running"
    planner_mode: str = "gemini"
    final_summary: str = ""
    halted_reason: str | None = None
    steps: list[ExecutionStepResult] = Field(default_factory=list)
    extracted_artifacts: list[dict[str, Any]] = Field(default_factory=list)
