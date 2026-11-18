"""Resolve code, vault, and app-owned runtime paths.

This module is a dependency leaf: business modules may import paths from here
without importing the FastAPI composition root.
"""

import os
import sys
from pathlib import Path

import vault_config


def _resolve_gateway_dir() -> Path:
    """Return the static-resource root in source and PyInstaller builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        if sys.platform == "darwin" and meipass.name == "Frameworks":
            real_resources = meipass.parent / "Resources"
            if real_resources.is_dir():
                return real_resources.resolve()
        return meipass.resolve()
    return Path(__file__).parent.resolve()


def _default_app_state_dir() -> Path:
    """Return the OS-standard app-state directory, with env override."""
    env = os.environ.get("HUMAN_AI_STATE")
    if env:
        return Path(env).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "HumanAI"
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "HumanAI"
        return home / "AppData" / "Roaming" / "HumanAI"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "HumanAI"
    return home / ".local" / "share" / "HumanAI"


GATEWAY_DIR = _resolve_gateway_dir()
CODE_ROOT = GATEWAY_DIR.parent
DATA_HOME = vault_config.resolve_vault_root()
VAULT_DIR = DATA_HOME / "vault"
APP_STATE_DIR = _default_app_state_dir()
DATA_DIR = APP_STATE_DIR / "data"
CONFIG_DIR = APP_STATE_DIR / "config"
