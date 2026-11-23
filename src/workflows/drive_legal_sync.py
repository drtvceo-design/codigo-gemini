"""Read-only Google Drive legal & corporate document sync using the connected gdrive CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document
from pydantic import BaseModel, Field
from pypdf import PdfReader

from ..config import PINNED_DRIVE_RESOURCES, DriveResourceTarget, PlatformSettings, get_settings


class SyncedDriveItem(BaseModel):
    """Metadata and extracted intelligence from a pinned Google Drive file."""

    file_id: str
    name: str
    kind: str
    status: str
    local_path: str = ""
    size_bytes: int = 0
    page_or_key_count: int = 0
    preview_excerpt: str = ""
    structured_keys: list[str] = Field(default_factory=list)
    error: str = ""


class DriveLegalSyncSummary(BaseModel):
    """Summary of read-only sync across pinned CNS Juzgado 3° & corporate Drive files."""

    synced_at: str
    gdrive_cli_available: bool
    total_resources: int
    succeeded_count: int
    report_path: str = ""
    items: list[SyncedDriveItem] = Field(default_factory=list)


def _extract_file_intelligence(path: Path, kind: str) -> tuple[int, list[str], str]:
    """Extract page/key counts and a concise preview without mutating the source file."""
    if kind == "json":
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            keys = list(data.keys())[:20]
            excerpt = json.dumps(data, ensure_ascii=False)[:700]
            return len(data), keys, excerpt
        if isinstance(data, list):
            excerpt = json.dumps(data[:2], ensure_ascii=False)[:700]
            return len(data), ["list_items"], excerpt
        return 1, [], str(data)[:700]

    if kind == "pdf":
        reader = PdfReader(str(path))
        pages = len(reader.pages)
        text_parts: list[str] = []
        for pg in reader.pages[:3]:
            extracted = (pg.extract_text() or "").strip()
            if extracted:
                text_parts.append(extracted)
        excerpt = "\n".join(text_parts).strip()[:700]
        return pages, [f"pages:{pages}"], excerpt

    if kind == "docx":
        doc = Document(str(path))
        paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        excerpt = "\n".join(paras[:10])[:700]
        return len(paras), [f"paragraphs:{len(paras)}"], excerpt

    # Markdown / HTML / plain text
    content = path.read_text(encoding="utf-8", errors="replace").strip()
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    headings = [ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")][:12]
    return len(lines), headings, content[:700]


def sync_pinned_drive_resources(
    *,
    resources: list[DriveResourceTarget] | None = None,
    settings: PlatformSettings | None = None,
) -> DriveLegalSyncSummary:
    """Fetch pinned Google Drive resources via read-only gdrive CLI and build an indexed JSON digest."""
    cfg = settings or get_settings()
    targets = resources or PINNED_DRIVE_RESOURCES
    sync_dir = cfg.output_dir / "drive_sync"
    files_dir = sync_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    gdrive_bin = shutil.which("gdrive")
    items: list[SyncedDriveItem] = []

    for res in targets:
        dest = files_dir / res.name
        if not gdrive_bin:
            items.append(
                SyncedDriveItem(
                    file_id=res.file_id,
                    name=res.name,
                    kind=res.kind,
                    status="gdrive_unavailable",
                    error="El binario 'gdrive' no está en PATH.",
                )
            )
            continue

        cmd = (
            [gdrive_bin, "readonly", "export", res.file_id, str(dest), "--format", "md"]
            if res.export_mode == "export_md"
            else [gdrive_bin, "readonly", "download", res.file_id, "--out", str(dest)]
        )

        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=45)
        if proc.returncode != 0 or not dest.exists():
            items.append(
                SyncedDriveItem(
                    file_id=res.file_id,
                    name=res.name,
                    kind=res.kind,
                    status="error",
                    error=(proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:240],
                )
            )
            continue

        try:
            count, keys, excerpt = _extract_file_intelligence(dest, res.kind)
            items.append(
                SyncedDriveItem(
                    file_id=res.file_id,
                    name=res.name,
                    kind=res.kind,
                    status="synced",
                    local_path=str(dest),
                    size_bytes=dest.stat().st_size,
                    page_or_key_count=count,
                    structured_keys=keys,
                    preview_excerpt=excerpt,
                )
            )
        except Exception as parse_err:
            items.append(
                SyncedDriveItem(
                    file_id=res.file_id,
                    name=res.name,
                    kind=res.kind,
                    status="downloaded_parse_warning",
                    local_path=str(dest),
                    size_bytes=dest.stat().st_size,
                    error=str(parse_err)[:200],
                )
            )

    report_path = sync_dir / "latest_drive_digest.json"
    ok_count = sum(1 for it in items if it.status in {"synced", "downloaded_parse_warning"})
    summary = DriveLegalSyncSummary(
        synced_at=datetime.now(timezone.utc).isoformat(),
        gdrive_cli_available=bool(gdrive_bin),
        total_resources=len(items),
        succeeded_count=ok_count,
        report_path=str(report_path),
        items=items,
    )
    report_path.write_text(json.dumps(summary.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
