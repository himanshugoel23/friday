"""``friday docs eval <folder>``: run the document reader on local files and print the fields.

Nothing is stored (no database, no copies); document text and bytes are never logged. It uses the
provider in FRIDAY_DOCS_VISION_PROVIDER (use ``openai`` to measure accuracy: it calls the real API
with the existing OPENAI_API_KEY, so it costs a little). Exit: 0 ok, 2 cannot run.
See docs/DOC_SAMPLE_SET.md for which documents to photograph.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
from pathlib import Path
from typing import Any

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def register(sub: Any) -> None:
    d = sub.add_parser("docs", help="document reader tools (nothing is stored)")
    dsub = d.add_subparsers(dest="docs_cmd")
    e = dsub.add_parser("eval", help="read every photo/PDF in a folder, print field-level results")
    e.add_argument("folder")
    e.add_argument("--json", action="store_true", help="machine-readable output")


def _files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTS)


async def _read_all(files: list[Path], pipeline: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in files:
        mime = mimetypes.guess_type(p.name)[0] or ""
        outcome = await pipeline.process("eval", p.read_bytes(), mime)
        row: dict[str, Any] = {"file": p.name, "outcome": outcome.kind}
        doc = outcome.document
        if doc is not None:
            row.update(
                doc_type=doc.doc_type.value,
                confidence=round(doc.confidence, 2),
                injection_flag=doc.injection_flag,
                fields={
                    k: {
                        "value": f.value,
                        "confidence": round(f.confidence, 2),
                        "needs_confirm": f.needs_confirm,
                    }
                    for k, f in doc.fields.items()
                },
                issues=[getattr(i, "code", str(i)) for i in outcome.issues],
            )
        out.append(row)
    return out


def run_command(args: argparse.Namespace) -> int:
    if getattr(args, "docs_cmd", None) != "eval":
        print(__doc__)
        return 0
    from friday.core.clock import SystemClock
    from friday.core.config import Settings
    from friday.core.scale import MemoryCache
    from friday.docunderstand.pipeline import DocLimits, DocumentPipeline
    from friday.docunderstand.ports import build_vision

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"not a folder: {folder}")
        return 2
    files = _files(folder)
    if not files:
        print(f"no photos or PDFs (jpg, png, webp, pdf) in {folder}")
        return 2
    s = Settings()
    provider = (s.docs_vision_provider or "none").strip().lower()
    if provider in ("", "none", "off"):
        print("FRIDAY_DOCS_VISION_PROVIDER is 'none': set it to 'openai'. Not running.")
        return 2
    clock = SystemClock()
    limits = DocLimits(
        max_bytes=s.docs_max_bytes, max_pages=s.docs_max_pages, daily_cap=10**6,
        confirm_below=s.docs_confirm_below, pending_days=s.docs_pending_days,
    )  # fmt: skip
    pipeline = DocumentPipeline(build_vision(provider, s), clock, MemoryCache(clock), limits)
    rows = asyncio.run(_read_all(files, pipeline))
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    print(f"provider={provider} model={s.docs_vision_model} files={len(rows)} (nothing stored)")
    for r in rows:
        print(f"\n{r['file']}: {r['outcome']}", end="")
        if "doc_type" in r:
            flag = "  INJECTION-FLAG" if r["injection_flag"] else ""
            print(f"  type={r['doc_type']} confidence={r['confidence']}{flag}")
            for k, f in r["fields"].items():
                mark = "  (needs confirm)" if f["needs_confirm"] else ""
                print(f"  {k:<18} {f['value']}  [{f['confidence']}]{mark}")
            if r["issues"]:
                print(f"  issues: {', '.join(r['issues'])}")
        else:
            print()
    return 0
