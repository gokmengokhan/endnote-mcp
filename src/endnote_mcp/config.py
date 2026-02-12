"""Configuration loader for endnote-mcp."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path

import yaml


def get_config_dir() -> Path:
    """Return the platform-appropriate config directory."""
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "endnote-mcp"
    elif platform.system() == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / "endnote-mcp"
    else:
        return Path.home() / ".config" / "endnote-mcp"


def get_default_config_path() -> Path:
    """Return the default config file path."""
    return get_config_dir() / "config.yaml"


# Legacy path (for backwards compatibility with pre-1.0 installs)
_LEGACY_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"


@dataclass
class Config:
    endnote_xml: Path
    pdf_dir: Path
    db_path: Path
    max_pdf_pages: int = 30

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        """Load configuration from a YAML file.

        Resolution order:
        1. Explicit *path* argument
        2. ENDNOTE_MCP_CONFIG environment variable
        3. Platform config dir (~/.config/endnote-mcp/config.yaml or equivalent)
        4. Legacy config.yaml next to pyproject.toml
        """
        if path is None:
            path = os.environ.get("ENDNOTE_MCP_CONFIG")

        if path is None:
            default = get_default_config_path()
            if default.exists():
                path = default
            elif _LEGACY_CONFIG_PATH.exists():
                path = _LEGACY_CONFIG_PATH
            else:
                raise FileNotFoundError(
                    f"No configuration found.\n"
                    f"Run 'endnote-mcp setup' to configure your library."
                )

        path = Path(path).expanduser().resolve()

        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}\n"
                "Run 'endnote-mcp setup' to configure your library."
            )

        with open(path) as f:
            raw = yaml.safe_load(f)

        endnote_xml = Path(raw["endnote_xml"]).expanduser().resolve()
        pdf_dir = Path(raw["pdf_dir"]).expanduser().resolve()

        db_path_raw = raw.get("db_path")
        if db_path_raw:
            db_path = Path(db_path_raw).expanduser().resolve()
        else:
            db_path = get_config_dir() / "library.db"

        return cls(
            endnote_xml=endnote_xml,
            pdf_dir=pdf_dir,
            db_path=db_path,
            max_pdf_pages=int(raw.get("max_pdf_pages", 30)),
        )
