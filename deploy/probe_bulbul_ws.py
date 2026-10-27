"""Live TTS latency probe: Bulbul v3 WebSocket vs our HTTP streaming vs REST (costs a few paise).

    .venv/bin/python deploy/probe_bulbul_ws.py [--json out.json]

Four paths per line, interleaved so network drift hits all equally, same voice / pace / temperature /
8 kHz / pronunciation dictionary (if var/tts/dict_id.json or the env id exists) as Friday's call leg:
  REST        SarvamTTS.synthesize           (POST /text-to-speech)
  HTTP stream SarvamTTS.synthesize_stream    (POST /text-to-speech/stream, what the call uses)
  WS warm     one persistent wss://api.sarvam.ai/text-to-speech/ws connection reused for all lines
              (what a call would do after the first line); first audio is measured from sending the text
  WS cold     a new connection + config per line; first audio from the connect start (worst case)
WS protocol (docs.sarvam.ai/api-reference/text-to-speech/stream, read 2026-10-22): query model,
send_completion_event; client {"type":"config","data":{...}}, {"type":"text","data":{"text"}},
{"type":"flush"}; server {"type":"audio","data":{"audio":b64}}, {"type":"event","data":{"event_type":"final"}}.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_voice_common import Abort, check_status, summary  # noqa: E402

from friday.core.config import Settings  # noqa: E402
from friday.core.interfaces import ProviderError  # noqa: E402
from friday.core.models import Language  # noqa: E402
from friday.voice.tts.sarvam import build_sarvam_tts  # noqa: E402

WS_URL = "wss://api.sarvam.ai/text-to-speech/ws"
LINES = [
    "Haan ji, main Friday bol rahi hoon, Himanshu sir ki assistant.",
    "Haircut ke teen sau pachaas rupaye lagte hain ji.",
    "Kal shaam paanch baje ka slot khaali hai, kya main book kar doon?",
    "Theek hai ji, main unko bata dungi, aap tab tak line par bane rahiye.",
    "Beard trim aur haircut dono karwane hain toh kul chaar sau rupaye honge.",
    "Maaf kijiye, mujhe aapki baat ek baar phir se samajhni hai, kya aap dohra sakte hain?",
    "Sunday ko hum subah dus baje se raat aath baje tak khule rehte hain.",
    "Bilkul sir, main abhi calendar dekh kar aapko bata deti hoon ki kaun sa time free hai.",
    "Dhanyavaad ji, aapka din shubh ho, Himanshu sir ko main yeh message de dungi.",
    "Ji, unhe parso dopahar do baje aana hai, kya aap mujhe apna naam aur number bata sakte hain? Main unhe confirm kar dungi, aur time badalna ho toh batana.",
]


async def one_ws(key: str, cfg: dict, text: str, ws=None, timeout: float = 20.0) -> dict:
    """Run one line over the WebSocket. Opens (cold) or reuses (warm) the connection."""
    import websockets
    t_start = time.perf_counter()
    own = ws is None
    connect_ms = 0.0
    if own:
        try:
            ws = await websockets.connect(
                f"{WS_URL}?model={cfg['model']}&send_completion_event=true",
                additional_headers={"Api-Subscription-Key": key}, max_size=None)
        except websockets.exceptions.InvalidStatus as e:
            check_status(e.response.status_code, "TTS websocket handshake")
            return {"error": f"handshake HTTP {e.response.status_code}"}
        connect_ms = (time.perf_counter() - t_start) * 1000
        await ws.send(json.dumps({"type": "config", "data": cfg}))
    t_text = time.perf_counter()
    await ws.send(json.dumps({"type": "text", "data": {"text": text}}))
    await ws.send(json.dumps({"type": "flush"}))
    first = None
    nbytes = 0
    n_chunks = 0
    head = b""
    ev = []
    err = None
    t_final = None
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout)
            m = json.loads(raw)
            if m.get("type") == "audio":
                b = base64.b64decode(m["data"]["audio"])
                if first is None:
                    first = time.perf_counter()
                    head = b[:12]
                nbytes += len(b)
                n_chunks += 1
            elif m.get("type") == "error":
                err = m.get("data")
                break
            else:
                ev.append(m)
                if (m.get("data") or {}).get("event_type") == "final":
                    t_final = time.perf_counter()
                    break
    except asyncio.TimeoutError:
        err = "timeout waiting for final event"
    if own:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
    hdr = 44 if head[:4] == b"RIFF" else 0
    return {
        "first_ms": (first - (t_start if own else t_text)) * 1000 if first else None,
        "first_from_text_ms": (first - t_text) * 1000 if first else None,
        "connect_ms": connect_ms,
        "total_ms": ((t_final or time.perf_counter()) - (t_start if own else t_text)) * 1000,
        "audio_s": max(0, nbytes - hdr) / 16000, "chunks": n_chunks, "header": head[:4].hex(),
        "error": err, "events": ev[:2],
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--codec", default="linear16")
    args = ap.parse_args()
    settings = Settings()
    if not settings.sarvam_api_key:
        print("SARVAM_API_KEY is not set")
        return 2
    key = settings.sarvam_api_key.get_secret_value()
    tts = build_sarvam_tts(SimpleNamespace(settings=settings))  # type: ignore[arg-type]
    lang = Language.HINGLISH
    voice = tts.voice_for(lang)
    body = tts.payload("x", lang, voice)
    cfg = {"model": body["model"], "language_code": body["target_language_code"], "speaker": body["speaker"],
           "pace": body["pace"], "speech_sample_rate": 8000, "output_audio_codec": args.codec}
    if "temperature" in body:
        cfg["temperature"] = body["temperature"]
    if "dict_id" in body:
        cfg["dict_id"] = body["dict_id"]
    print("settings used:", {k: (v if k != "dict_id" else "<set>") for k, v in cfg.items()},
          "| dictionary:", "ON" if "dict_id" in body else "OFF (no dict id in this sandbox)")
    rows: dict[str, list[dict]] = {k: [] for k in ("REST", "HTTP stream", "WS warm", "WS cold")}
    warm = None
    try:
        import websockets
        try:
            warm = await websockets.connect(f"{WS_URL}?model={cfg['model']}&send_completion_event=true",
                                            additional_headers={"Api-Subscription-Key": key}, max_size=None)
        except websockets.exceptions.InvalidStatus as e:
            check_status(e.response.status_code, "TTS websocket handshake")
            raise
        await warm.send(json.dumps({"type": "config", "data": cfg}))
        for i, text in enumerate(LINES):
            n = len(text)
            t = time.perf_counter()
            clip = await tts.synthesize(text, lang)
            ms = (time.perf_counter() - t) * 1000
            rows["REST"].append({"chars": n, "first_ms": ms, "total_ms": ms, "audio_s": (len(clip.data) - 44) / 16000})
            t = time.perf_counter()
            first, nb = None, 0
            async for pcm in tts.synthesize_stream(text, lang):
                first = first or (time.perf_counter() - t) * 1000
                nb += len(pcm)
            rows["HTTP stream"].append({"chars": n, "first_ms": first, "total_ms": (time.perf_counter() - t) * 1000, "audio_s": nb / 16000})
            r = await one_ws(key, cfg, text, ws=warm)
            r["chars"] = n
            rows["WS warm"].append(r)
            r = await one_ws(key, cfg, text)
            r["chars"] = n
            rows["WS cold"].append(r)
            print(i + 1, n, "chars |", " | ".join(
                f"{k} {v[-1].get('first_ms') and round(v[-1]['first_ms'])}/{round(v[-1].get('total_ms') or 0)}ms"
                + (f" ERR {v[-1]['error']}" if v[-1].get("error") else "") for k, v in rows.items()))
    except ProviderError as e:
        msg = str(e)
        print("PROVIDER ERROR:", msg[:200])
        if any(c in msg for c in ("401", "402")):
            print("ABORT: auth / credit")
    except Abort as e:
        print("ABORT:", e)
    finally:
        if warm is not None:
            await warm.close()
        await tts.aclose()
    print("\n== summary: first audio ms / total ms ==")
    for k, v in rows.items():
        ok = [r for r in v if not r.get("error")]
        print(f"{k:12s} first {summary([r.get('first_ms') for r in ok])} | total {summary([r.get('total_ms') for r in ok])} | errors {len(v) - len(ok)}"
              + (f" | audio s {sum(r['audio_s'] for r in ok) / max(1, len(ok)):.1f} avg, header {ok[0].get('header')}" if ok and k.startswith("WS") else ""))
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
