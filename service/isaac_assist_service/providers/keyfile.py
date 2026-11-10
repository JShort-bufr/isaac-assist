# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# NVIDIA API key loader. Logs presence only; never the key value.

"""Load an NVIDIA API key from a mode-0600 env file.

The process environment is intentionally not consulted. A key that is only
present as ``NVIDIA_API_KEY`` in the environment is ignored so the provider
fails closed unless the operator pointed ``NVIDIA_API_KEY_FILE`` at a
private file.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger("isaac_assist.providers")

_DEFAULT_KEY_FILE = "~/.config/bufrai/nvidia-api.env"


def nvidia_key_path() -> Path:
    raw = os.environ.get("NVIDIA_API_KEY_FILE", _DEFAULT_KEY_FILE)
    return Path(raw).expanduser()


def load_nvidia_api_key(path: Path | None = None) -> str | None:
    """Return the key, or None when the file is missing or not mode 0600.

    The key value is never written to the log. Callers must not log it either.
    """
    key_path = path if path is not None else nvidia_key_path()
    if not key_path.exists():
        logger.info("nvidia key file missing; key present: no")
        return None
    try:
        info = key_path.lstat()
    except OSError:
        logger.info("nvidia key file unreadable; key present: no")
        return None
    if stat.S_ISLNK(info.st_mode):
        logger.warning("nvidia key path is a symlink; refusing to load; key present: no")
        return None
    if not stat.S_ISREG(info.st_mode):
        logger.warning("nvidia key path is not a regular file; refusing to load; key present: no")
        return None
    mode = stat.S_IMODE(info.st_mode)
    if mode != 0o600:
        logger.warning(
            "nvidia key file mode is not 0600; refusing to load; key present: no"
        )
        return None

    try:
        text = key_path.read_text(encoding="utf-8")
    except OSError:
        logger.info("nvidia key file unreadable; key present: no")
        return None

    key = _parse_key(text)
    if not key:
        logger.info("nvidia key file has no NVIDIA_API_KEY assignment; key present: no")
        return None
    logger.info("nvidia key file accepted; key present: yes")
    return key


def _parse_key(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != "NVIDIA_API_KEY":
            continue
        return value.strip().strip('"').strip("'")
    return ""
