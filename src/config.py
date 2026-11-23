"""Centralized configuration, portal catalog, and Drive resource registry.

All credentials and API keys are read strictly from environment variables.
Never store secrets in source files.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.getenv("COMPUTER_USE_OUTPUT_DIR", str(REPO_ROOT / "output")))


class PortalTarget(BaseModel):
    """Metadata for an ecosystem web portal (public endpoints only, zero secrets)."""

    slug: str
    name: str
    category: Literal["universolife_room", "wordpress_portal"]
    public_url: str
    health_url: str
    wp_rest_url: str | None = None
    description: str


class DriveResourceTarget(BaseModel):
    """Metadata for a pinned Google Drive project resource."""

    file_id: str
    name: str
    kind: Literal["json", "pdf", "docx", "gdoc_md", "html", "audio"]
    export_mode: Literal["download", "export_md"] = "download"
    description: str


class PlatformSettings(BaseModel):
    """Runtime settings loaded from environment variables."""

    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip())
    gemini_model: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip())
    chrome_executable_path: str = Field(
        default_factory=lambda: os.getenv("CHROME_EXECUTABLE_PATH", "/usr/bin/google-chrome").strip()
    )
    headless: bool = Field(
        default_factory=lambda: os.getenv("COMPUTER_USE_HEADLESS", "true").strip().lower() not in {"0", "false", "no"}
    )
    viewport_width: int = Field(default_factory=lambda: int(os.getenv("COMPUTER_USE_VIEWPORT_WIDTH", "1280")))
    viewport_height: int = Field(default_factory=lambda: int(os.getenv("COMPUTER_USE_VIEWPORT_HEIGHT", "800")))
    zapier_webhook_url: str = Field(default_factory=lambda: os.getenv("ZAPIER_WEBHOOK_URL", "").strip())
    zapier_dry_run: bool = Field(
        default_factory=lambda: os.getenv("ZAPIER_DRY_RUN", "true").strip().lower() not in {"0", "false", "no"}
    )
    output_dir: Path = Field(default_factory=lambda: OUTPUT_DIR)


ECOSYSTEM_PORTALS: list[PortalTarget] = [
    # 4 Private Rooms on api.universolife.com
    PortalTarget(
        slug="ava-vivo",
        name="Cabina Video y Voz en Vivo (AVA & Serena)",
        category="universolife_room",
        public_url="https://api.universolife.com/ava_vivo.php",
        health_url="https://api.universolife.com/ava_vivo.php",
        description="Cabina interactiva de cámara y voz neuronal manos libres.",
    ),
    PortalTarget(
        slug="santuario-serena",
        name="Santuario Psicóloga Serena",
        category="universolife_room",
        public_url="https://api.universolife.com/refugio.php",
        health_url="https://api.universolife.com/refugio.php",
        description="Refugio personal y bitácora cifrada AES-256-GCM.",
    ),
    PortalTarget(
        slug="portal-familia",
        name="Portal Familiar (Alejandra y Daniel)",
        category="universolife_room",
        public_url="https://api.universolife.com/familia.php",
        health_url="https://api.universolife.com/familia.php",
        description="Galería familiar privada y comunicación directa.",
    ),
    PortalTarget(
        slug="boveda-central",
        name="Bóveda Central & Cabina Gemini 24/7",
        category="universolife_room",
        public_url="https://api.universolife.com/",
        health_url="https://api.universolife.com/",
        description="Consola central API UniversoLife y rotación de llaves.",
    ),
    # 8 WordPress Portals
    PortalTarget(
        slug="wp-info-universolife",
        name="Hub Central AVA & Bots",
        category="wordpress_portal",
        public_url="https://info.universolife.com/",
        health_url="https://info.universolife.com/",
        wp_rest_url="https://info.universolife.com/wp-json/",
        description="Consola central UniversoLife, avatares y Grafeno Boliviano.",
    ),
    PortalTarget(
        slug="wp-index-universolife",
        name="Índice UniversoLife",
        category="wordpress_portal",
        public_url="https://index.universolife.com/",
        health_url="https://index.universolife.com/",
        wp_rest_url="https://index.universolife.com/wp-json/",
        description="Índice Fiduciario Panas Token y gobernanza.",
    ),
    PortalTarget(
        slug="wp-casa-red",
        name="Casa Red S.R.L. (RWA)",
        category="wordpress_portal",
        public_url="https://casa-red.universolife.com/",
        health_url="https://casa-red.universolife.com/",
        wp_rest_url="https://casa-red.universolife.com/wp-json/",
        description="Portal inmobiliario y tokenización de activos reales.",
    ),
    PortalTarget(
        slug="wp-token-drtapiavargas",
        name="Portal Tokens & NFTs Algorand",
        category="wordpress_portal",
        public_url="https://token.drtapiavargas.com/",
        health_url="https://token.drtapiavargas.com/",
        wp_rest_url="https://token.drtapiavargas.com/wp-json/",
        description="División Web3 Algorand, servicios y activos digitales.",
    ),
    PortalTarget(
        slug="wp-karapanza",
        name="Tienda Karapanza",
        category="wordpress_portal",
        public_url="https://karapanza.in/",
        health_url="https://karapanza.in/",
        wp_rest_url="https://karapanza.in/wp-json/",
        description="WooCommerce nacional con pagos locales y despachos.",
    ),
    PortalTarget(
        slug="wp-boliviachic",
        name="Shop BoliviaChic",
        category="wordpress_portal",
        public_url="https://shop.boliviachic.com/",
        health_url="https://shop.boliviachic.com/",
        wp_rest_url="https://shop.boliviachic.com/wp-json/",
        description="Fábrica de Bloques, NFTs y NOWPayments WooCommerce.",
    ),
    PortalTarget(
        slug="wp-eleusis",
        name="Eleusis Graphenic Hub",
        category="wordpress_portal",
        public_url="https://eleusis.apple-war.com/",
        health_url="https://eleusis.apple-war.com/",
        wp_rest_url="https://eleusis.apple-war.com/wp-json/",
        description="Portal científico y tecnológico de Eleusis Ícono.",
    ),
    PortalTarget(
        slug="wp-kuchiuyas",
        name="Crónicas Los Kuchiuyas",
        category="wordpress_portal",
        public_url="https://porno.kuchiuyas.com/",
        health_url="https://porno.kuchiuyas.com/",
        wp_rest_url="https://porno.kuchiuyas.com/wp-json/",
        description="Universo literario satírico picaresco.",
    ),
]


PINNED_DRIVE_RESOURCES: list[DriveResourceTarget] = [
    DriveResourceTarget(
        file_id="10_KVly1HZfNqSYuX5lBsFbVXa3QMxMkQ",
        name="00_DICTAMEN_AUDITORIA_EFECTO_DIFERIDO_Y_MULTA.json",
        kind="json",
        export_mode="download",
        description="Dictamen de auditoría técnica sobre efecto diferido y multa procesal.",
    ),
    DriveResourceTarget(
        file_id="1Ba99cpbieFDYmnQ_9uO8kyUW9W7wrTO9",
        name="00_REPORTE_ASOCIACION_DOCS_Y_LEYES_CNS_JUZGADO_3.json",
        kind="json",
        export_mode="download",
        description="Asociación estructurada de documentos y normativa CNS Juzgado 3°.",
    ),
    DriveResourceTarget(
        file_id="1ZgB3Gp2ZnXGlrUeHW_I6TMrsqQ7vv7LV",
        name="00_CATALOGO_CENTRALIZADO_CARLA_LOAYZA.json",
        kind="json",
        export_mode="download",
        description="Catálogo documental centralizado causa Carla Loayza.",
    ),
    DriveResourceTarget(
        file_id="10ECGZt8KlMEbvXx3SEjk77MGBGWZN_JlWNVWv4_5g5U",
        name="DOCUMENTO_PRIVADO_CONCILIACION_DEFINITIVA.md",
        kind="gdoc_md",
        export_mode="export_md",
        description="Documento privado de conciliación definitiva y garantía solidaria.",
    ),
    DriveResourceTarget(
        file_id="1Q1i7dQcz5NZQmoX3SVh5uO4DNM_yOc08",
        name="00_APARTADO_ESPECIAL_CNS_JUZGADO_3_LABORAL_QUE_GANAMOS_Y_QUE_FALTA_A4.pdf",
        kind="pdf",
        export_mode="download",
        description="Apartado ejecutivo CNS Juzgado 3° Laboral (logros y pendientes).",
    ),
    DriveResourceTarget(
        file_id="1DUwdSf1YKqGjrvMHk7p7qfOLtw0TMzEF",
        name="Memorial_Constancia_Recaudos_e_Integracion_Testimonio_Auto_34_CNS_A4.pdf",
        kind="pdf",
        export_mode="download",
        description="Memorial NUREJ 10140091 para Juzgado 3° de Trabajo Sucre.",
    ),
]


def get_settings() -> PlatformSettings:
    """Return fresh platform settings."""
    settings = PlatformSettings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    return settings
