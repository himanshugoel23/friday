"""Live STT latency probe: Sarvam realtime WebSocket (several settings) vs REST vs our streaming client.

    .venv/bin/python deploy/probe_saaras_realtime.py [--audio-dir DIR] [--only NAME,...]

Protocol (docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws, read 2026-10-22):
GET wss://api.sarvam.ai/speech-to-text-realtime/ws?language_code&model=saaras:v3-realtime|saaras:v4
&stream_type=fast|balanced|simulated&encoding=mulaw&sample_rate=8000&silence_duration_ms=...
header Api-Subscription-Key; client {"event":"audio_input","audio":b64}; server session.begin,
vad.speech_start|end, transcript.partial|final, error, session.end.

Test utterances are synthesised with Sarvam TTS (a male voice, 8 kHz), converted to mu-law as the call
path does, and streamed in 20 ms frames in REAL time with 0.4 s of lead silence and digital-silence
tail. "End of speech" = the moment the last speech frame has been sent. Synthetic speech: no noise,
no accents, not a phone line.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_voice_common import Abort, api_key, best_wer, check_status, norm, summary  # noqa: E402

from friday.core.models import AudioClip  # noqa: E402
from friday.voice.audio import pcm16_to_ulaw, pcm16_to_wav, wav_to_pcm16  # noqa: E402
from friday.voice.stt.sarvam import SarvamSTT  # noqa: E402
from friday.voice.stt.sarvam_stream import SarvamStreamSTT, StreamSTTConfig  # noqa: E402

URL = "wss://api.sarvam.ai/speech-to-text-realtime/ws"
# (id, Roman text for TTS, acceptable reference spellings for scoring)
UTTS = [
    ("u01", "haircut ke kitne paise lagenge", ["haircut ke kitne paise lagenge", "हेयरकट के कितने पैसे लगेंगे"]),
    ("u02", "kal shaam paanch baje ka slot hai", ["kal shaam paanch baje ka slot hai", "कल शाम पांच बजे का स्लॉट है", "कल शाम 5 बजे का स्लॉट है"]),
    ("u03", "haan ji bataiye", ["haan ji bataiye", "हाँ जी बताइए", "हां जी बताइये"]),
    ("u04", "chaar sau rupaye", ["chaar sau rupaye", "चार सौ रुपये", "400 रुपये", "₹400"]),
    ("u05", "nahi sir abhi free nahi hain", ["nahi sir abhi free nahi hain", "नहीं सर अभी फ्री नहीं हैं"]),
    ("u06", "theek hai main parso aa jaunga", ["theek hai main parso aa jaunga", "ठीक है मैं परसों आ जाऊंगा"]),
    ("u07", "beard trim aur haircut dono karna hai", ["beard trim aur haircut dono karna hai", "बियर्ड ट्रिम और हेयरकट दोनों करना है", "बीयर्ड ट्रिम और हेयरकट दोनों करना है"]),
    ("u08", "kya aap sunday ko khule hain", ["kya aap sunday ko khule hain", "क्या आप संडे को खुले हैं", "क्या आप रविवार को खुले हैं"]),
    ("u09", "rukiye main calendar dekh ke batata hoon", ["rukiye main calendar dekh ke batata hoon", "रुकिए मैं कैलेंडर देख के बताता हूं"]),
    ("u10", "ji bilkul main shaam ko call karta hoon", ["ji bilkul main shaam ko call karta hoon", "जी बिल्कुल मैं शाम को कॉल करता हूं"]),
]
# name -> query overrides for the raw WebSocket client
VARIANTS: dict[str, dict[str, str]] = {
    "v3rt fast sil300 (current)": {"model": "saaras:v3-realtime", "stream_type": "fast", "silence_duration_ms": "300"},
    "v3rt fast sil150": {"model": "saaras:v3-realtime", "stream_type": "fast", "silence_duration_ms": "150"},
    "v3rt fast sil500 (doc default)": {"model": "saaras:v3-realtime", "stream_type": "fast", "silence_duration_ms": "500"},
    "v3rt balanced sil300": {"model": "saaras:v3-realtime", "stream_type": "balanced", "silence_duration_ms": "300"},
    "v4 fast sil300": {"model": "saaras:v4", "stream_type": "fast", "silence_duration_ms": "300"},
}
LEAD_MS, TAIL_MS, FRAME = 400, 3500, 160  # 160 bytes = 20 ms of 8 kHz mu-law / 20 ms of silence


def synth(key: str, audio_dir: Path) -> dict[str, bytes]:
    """8 kHz PCM16 per utterance (cached on disk). Male voice 'aditya', bulbul:v3, pace 1.0."""
    out: dict[str, bytes] = {}
    for uid, text, _ in UTTS:
        f = audio_dir / f"{uid}.wav"
        if not f.exists():
            r = httpx.post(
                "https://api.sarvam.ai/text-to-speech",
                headers={"api-subscription-key": key},
                json={"text": text, "target_language_code": "hi-IN", "speaker": "aditya",
                      "model": "bulbul:v3", "pace": 1.0, "speech_sample_rate": 8000},
                timeout=30,
            )
            check_status(r.status_code, "text-to-speech (test audio)")
            r.raise_for_status()
            f.write_bytes(base64.b64decode(r.json()["audios"][0]))
        pcm, rate = wav_to_pcm16(f.read_bytes())
        assert rate == 8000, rate
        out[uid] = pcm
    return out


def trim(pcm: bytes) -> bytes:
    """Cut leading/trailing near-silence so 'end of speech' is the real end of the words."""
    import array
    a = array.array("h", pcm)
    thr = 300
    s = next((i for i, v in enumerate(a) if abs(v) > thr), 0)
    e = next((i for i in range(len(a) - 1, -1, -1) if abs(a[i]) > thr), len(a) - 1)
    return pcm[max(0, s - 160) * 2 : (min(len(a), e + 160)) * 2]


async def run_raw(key: str, query: dict[str, str], pcm: bytes) -> dict:
    import websockets
    q = {"language_code": "hi-IN", "encoding": "mulaw", "sample_rate": "8000", "mode": "transcribe", **query}
    t_open = time.perf_counter()
    try:
        ws = await websockets.connect(f"{URL}?{urlencode(q)}", additional_headers={"Api-Subscription-Key": key}, max_size=None)
    except websockets.exceptions.InvalidStatus as e:
        check_status(e.response.status_code, "STT websocket handshake")
        return {"error": f"handshake HTTP {e.response.status_code}"}
    ev: list[tuple[float, dict]] = []
    t0 = time.perf_counter()
    first = json.loads(await asyncio.wait_for(ws.recv(), 5))
    connect_ms = (time.perf_counter() - t_open) * 1000
    if first.get("event") != "session.begin":
        await ws.close()
        return {"error": f"first message {first}"}
    done = asyncio.Event()

    async def reader() -> None:
        try:
            async for raw in ws:
                m = json.loads(raw)
                ev.append((time.perf_counter(), m))
                if m.get("event") == "error":
                    done.set()
        except Exception:  # noqa: BLE001
            pass
        done.set()

    rt = asyncio.ensure_future(reader())
    ulaw = pcm16_to_ulaw(b"\x00\x00" * 8 * LEAD_MS + pcm + b"\x00\x00" * 8 * TAIL_MS)
    n_lead = 8 * LEAD_MS
    n_speech_end = n_lead + len(pcm) // 2
    start = time.perf_counter()
    t_speech_start = start + n_lead / 8000
    t_end = start + n_speech_end / 8000
    n_frames = len(ulaw) // FRAME
    sent_final = False
    for i in range(n_frames):
        due = start + i * 0.02
        d = due - time.perf_counter()
        if d > 0:
            await asyncio.sleep(d)
        await ws.send(json.dumps({"event": "audio_input", "audio": base64.b64encode(ulaw[i * FRAME:(i + 1) * FRAME]).decode()}))
        if time.perf_counter() > t_end + 0.2 and any(m.get("event") == "transcript.final" for _, m in ev):
            sent_final = True
            break
        if done.is_set():
            break
    await asyncio.sleep(0.15)
    rt.cancel()
    try:
        await ws.close()
    except Exception:  # noqa: BLE001
        pass
    errs = [m for _, m in ev if m.get("event") == "error"]
    finals = [(t, m) for t, m in ev if m.get("event") == "transcript.final"]
    partials = [(t, m) for t, m in ev if m.get("event") == "transcript.partial"]
    vad_end = [t for t, m in ev if m.get("event") == "vad.speech_end"]
    ms = lambda t: (t - t_end) * 1000  # noqa: E731
    final_text = " ".join(str(m.get("text") or "") for _, m in finals).strip()
    fin_t = finals[-1][0] if finals else None
    stable = None  # first moment a partial already equalled the final text
    if finals:
        for t, m in partials:
            if norm(str(m.get("text") or "")) == norm(final_text):
                stable = ms(t)
                break
    return {
        "connect_ms": connect_ms,
        "first_partial_ms": (partials[0][0] - t_speech_start) * 1000 if partials else None,
        "first_partial_after_end_ms": ms(partials[0][0]) if partials and partials[0][0] > t_end else None,
        "stable_partial_ms": stable,
        "vad_end_ms": ms(vad_end[0]) if vad_end else None,
        "final_ms": ms(fin_t) if fin_t else None,
        "n_finals": len(finals), "n_partials": len(partials),
        "text": final_text, "last_partial": str(partials[-1][1].get("text")) if partials else "",
        "error": errs[0] if errs else None, "early_exit": sent_final, "t0": t0,
    }


async def run_client(key: str, pcm: bytes) -> dict:
    """The production client (friday.voice.stt.sarvam_stream.SarvamStreamSTT) with its default config."""
    ev: dict[str, list] = {"p": [], "f": [], "e": []}
    cl = SarvamStreamSTT(
        StreamSTTConfig(api_key=key),
        on_partial=lambda t, l, i: ev["p"].append((time.perf_counter(), t)),
        on_final=lambda t, l, c, i: ev["f"].append((time.perf_counter(), t)),
        on_speech_end=lambda i: ev["e"].append(time.perf_counter()),
    )
    if not await cl.start():
        return {"error": "client could not start"}
    ulaw = pcm16_to_ulaw(b"\x00\x00" * 8 * LEAD_MS + pcm + b"\x00\x00" * 8 * TAIL_MS)
    n_lead = 8 * LEAD_MS
    start = time.perf_counter()
    t_ss = start + n_lead / 8000
    t_end = start + (n_lead + len(pcm) // 2) / 8000
    for i in range(len(ulaw) // FRAME):
        d = start + i * 0.02 - time.perf_counter()
        if d > 0:
            await asyncio.sleep(d)
        cl.feed(ulaw[i * FRAME:(i + 1) * FRAME])
        if ev["f"] and time.perf_counter() > t_end + 0.2:
            break
    await asyncio.sleep(0.15)
    await cl.aclose()
    txt = " ".join(t for _, t in ev["f"]).strip()
    stable = next((((t - t_end) * 1000) for t, p in ev["p"] if txt and norm(p) == norm(txt)), None)
    return {
        "first_partial_ms": (ev["p"][0][0] - t_ss) * 1000 if ev["p"] else None,
        "stable_partial_ms": stable,
        "vad_end_ms": (ev["e"][0] - t_end) * 1000 if ev["e"] else None,
        "final_ms": (ev["f"][-1][0] - t_end) * 1000 if ev["f"] else None,
        "text": txt, "error": None,
    }


async def run_rest(key: str, pcm: bytes) -> dict:
    """REST saaras:v4 exactly as SarvamSTT.transcribe does, on speech + 340 ms of silence
    (the speculative 'early STT' clip: the call leg fires it 340 ms into the pause)."""
    stt = SarvamSTT(key)
    clip = AudioClip(data=pcm16_to_wav(b"\x00\x00" * 1600 + pcm + b"\x00\x00" * 8 * 340, 8000), mime="audio/wav", sample_rate=8000)
    t = time.perf_counter()
    try:
        r = await stt.transcribe(clip)
    except Exception as e:  # noqa: BLE001
        code = getattr(getattr(e, "response", None), "status_code", None)
        check_status(code, "REST STT")
        if "402" in str(e) or "401" in str(e):
            raise Abort(f"REST STT: {e}") from e
        return {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    finally:
        await stt.aclose()
    ms = (time.perf_counter() - t) * 1000
    return {"rest_ms": ms, "text": r.text, "error": None}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-dir", default="/tmp/probe_audio")
    ap.add_argument("--only", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    key = api_key()
    ad = Path(args.audio_dir)
    ad.mkdir(parents=True, exist_ok=True)
    audio = {k: trim(v) for k, v in synth(key, ad).items()}
    for uid, t, _ in UTTS:
        print(f"{uid} {len(audio[uid]) / 16000:.2f}s  {t}")
    only = {x for x in args.only.split(",") if x}
    results: dict[str, list[dict]] = {}
    try:
        if not only or "rest" in only:
            rows = []
            for uid, _, refs in UTTS:
                r = await run_rest(key, audio[uid])
                r["uid"], r["wer"] = uid, best_wer(refs, r.get("text", "")) if not r.get("error") else None
                rows.append(r)
                print("REST", uid, f"{r.get('rest_ms', 0):.0f} ms", repr(r.get("text") or r.get("error")))
            results["rest"] = rows
        if not only or "client" in only:
            rows = []
            for uid, _, refs in UTTS:
                r = await run_client(key, audio[uid])
                r["uid"], r["wer"] = uid, best_wer(refs, r.get("text", "")) if not r.get("error") else None
                rows.append(r)
                print("CLIENT", uid, r.get("final_ms") and f"final {r['final_ms']:.0f}", repr(r.get("text") or r.get("error")))
            results["client"] = rows
        for name, q in VARIANTS.items():
            if only and name not in only and "raw" not in only:
                continue
            rows = []
            for uid, _, refs in UTTS:
                r = await run_raw(key, q, audio[uid])
                r["uid"], r["wer"] = uid, best_wer(refs, r.get("text", "")) if not r.get("error") else None
                rows.append(r)
                fm = r.get("final_ms")
                print(name, uid, f"final {fm:.0f}" if fm is not None else "no final", repr(r.get("text") or r.get("error")))
            results[name] = rows
    except Abort as e:
        print("ABORT:", e)
        results["_abort"] = [{"error": str(e)}]
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
    print("\n== summary (ms) ==")
    for name, rows in results.items():
        if name.startswith("_"):
            continue
        ok = [r for r in rows if not r.get("error")]
        w = [r["wer"] for r in ok if r.get("wer") is not None]
        if name == "rest":
            print(f"{name:34s} REST call {summary([r['rest_ms'] for r in ok])}  WER {sum(w) / max(1, len(w)):.2f}  errors {len(rows) - len(ok)}")
            continue
        print(f"{name:34s} final-after-end {summary([r.get('final_ms') for r in ok])} | first-partial-after-speech-start {summary([r.get('first_partial_ms') for r in ok])} | stable-partial {summary([r.get('stable_partial_ms') for r in ok])} | WER {sum(w) / max(1, len(w)):.2f} errors {len(rows) - len(ok)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
