"""Storage of generated images under IMG_ROOT.

Files are named with a random uuid4 hex, which is both the on-disk name and
the unguessable public URL path. Pure stdlib so the tests need no extras.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

# Names we create and the only names we ever serve back: 32 hex chars + .png.
_SAFE_NAME = re.compile(r"^[0-9a-f]{32}\.png$")


def images_root() -> Path:
    return Path(os.environ.get("IMG_ROOT", "/srv/images"))


def is_safe_image_name(name: str) -> bool:
    """Whether ``name`` is one of our generated names (and thus safe to open:
    no separators, no traversal, no dotfiles)."""
    return bool(_SAFE_NAME.match(name))


def save_image(data: bytes, root: Path) -> str:
    """Write PNG bytes under ``root`` with a fresh random name; returns the
    name (which doubles as the public URL path segment)."""
    root.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.png"
    (root / name).write_bytes(data)
    return name


def load_image(name: str, root: Path) -> bytes | None:
    """Read a previously generated image back, or ``None`` when the name is
    not one of ours or the file does not exist."""
    if not is_safe_image_name(name):
        return None
    path = root / name
    if not path.is_file():
        return None
    return path.read_bytes()


def delete_image(name: str, root: Path) -> bool:
    """Delete a generated image and its metadata sidecar. Returns ``True`` if
    the PNG existed and was removed, ``False`` for unsafe/unknown names. The
    ``.json`` sidecar is best-effort: a missing one is not an error."""
    if not is_safe_image_name(name):
        return False
    png = root / name
    if not png.is_file():
        return False
    png.unlink()
    sidecar = root / f"{name.rsplit('.', 1)[0]}.json"
    sidecar.unlink(missing_ok=True)
    return True
