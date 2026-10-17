"""`friday connectors pack-run DIR`: zip an explore run folder for the lead, with no secrets.

Allow-list only: state.json, menu.json, and per step screenshot.png / text.txt / elements.json /
meta.json, plus the BEFORE-login trace. Text and JSON go through scrub() again (phone numbers,
OTP-like codes, tokens, cookies). The AFTER-login trace holds the session's network log (cookies,
tokens) so it is left out unless ``include_post_login_trace`` is set. Anything else in the folder
(.env, storage state, stray files) is never copied.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from friday.connectors.explore import TRACE_1, TRACE_2, Sanitiser

_TOP_FILES = {"state.json", "menu.json"}
_STEP_FILES = {"screenshot.png", "text.txt", "elements.json", "meta.json"}


def _clean_bytes(path: Path, san: Sanitiser) -> bytes:
    if path.suffix == ".png" or path.suffix == ".zip":
        return path.read_bytes()
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json":
        try:
            return json.dumps(san.obj(json.loads(raw)), indent=1, ensure_ascii=False).encode()
        except ValueError:
            pass
    return san.text(raw).encode()


def pack_run(
    src: Path, dest: Path | None = None, include_post_login_trace: bool = False
) -> tuple[Path, list[str], list[str]]:
    """Returns (zip path, included names, skipped names)."""
    src = Path(src)
    if not src.is_dir():
        raise FileNotFoundError("run folder not found")
    dest = Path(dest) if dest else src.with_name(src.name.rstrip("/") + "-pack.zip")
    san = Sanitiser()
    wanted: list[Path] = [src / n for n in sorted(_TOP_FILES)]
    for d in sorted((src / "steps").glob("*")) if (src / "steps").is_dir() else []:
        wanted += [d / n for n in sorted(_STEP_FILES)]
    wanted.append(src / TRACE_1)
    if include_post_login_trace:
        wanted.append(src / TRACE_2)
    included: list[str] = []
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in wanted:
            if p.is_file() and not p.is_symlink():
                name = p.relative_to(src).as_posix()
                zf.writestr(name, _clean_bytes(p, san))
                included.append(name)
        zf.writestr("PACK_MANIFEST.txt", "Friday zomato-explore run pack\n" + "\n".join(included))
    wanted_names = {p.relative_to(src).as_posix() for p in wanted}
    skipped = sorted(
        p.relative_to(src).as_posix() for p in src.rglob("*")
        if p.is_file() and p.relative_to(src).as_posix() not in wanted_names
    )
    return dest, included, skipped
