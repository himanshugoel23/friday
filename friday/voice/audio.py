"""Audio utilities in pure Python (Python 3.13 removed ``audioop``).

* G.711 mu-law <-> PCM16 (Twilio Media Streams are 8 kHz mu-law)
* WAV pack/unpack, naive linear resampling, RMS / zero-crossing frame features
* tone + DTMF synthesis (in-band DTMF over a media stream)
* minimal Ogg page reader/writer (WhatsApp voice notes are Ogg/Opus)

PCM16 everywhere is little-endian signed 16-bit mono ``bytes``.
"""

from __future__ import annotations

import io
import math
import struct
import sys
import wave
from array import array
from dataclasses import dataclass, field

from friday.core.models import AudioClip

# =============================================================================== mu-law

_BIAS = 0x84
_CLIP = 32635


def _ulaw_encode_sample(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    if sample < 0:
        sample = -sample
    sample = min(sample, _CLIP) + _BIAS
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not (sample & mask):
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def _ulaw_decode_byte(byte: int) -> int:
    byte = ~byte & 0xFF
    sign = byte & 0x80
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    sample = (((mantissa << 3) + _BIAS) << exponent) - _BIAS
    return -sample if sign else sample


_DECODE_TABLE = array("h", (_ulaw_decode_byte(b) for b in range(256)))
_ENCODE_TABLE: bytes | None = None


def _encode_table() -> bytes:
    global _ENCODE_TABLE
    if _ENCODE_TABLE is None:
        _ENCODE_TABLE = bytes(
            _ulaw_encode_sample(s - 65536 if s >= 32768 else s) for s in range(65536)
        )
    return _ENCODE_TABLE


def _samples(pcm16: bytes) -> array:
    arr = array("h")
    arr.frombytes(pcm16[: len(pcm16) - (len(pcm16) % 2)])
    if sys.byteorder == "big":  # pragma: no cover
        arr.byteswap()
    return arr


def _to_bytes(arr: array) -> bytes:
    if sys.byteorder == "big":  # pragma: no cover
        arr = array("h", arr)
        arr.byteswap()
    return arr.tobytes()


def pcm16_to_ulaw(pcm16: bytes) -> bytes:
    table = _encode_table()
    return bytes(table[s & 0xFFFF] for s in _samples(pcm16))


def ulaw_to_pcm16(ulaw: bytes) -> bytes:
    return _to_bytes(array("h", (_DECODE_TABLE[b] for b in ulaw)))


# =============================================================================== WAV / PCM


def pcm16_to_wav(pcm16: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16)
    return buf.getvalue()


def wav_to_pcm16(data: bytes) -> tuple[bytes, int]:
    """WAV bytes -> (mono PCM16, sample_rate). Stereo is down-mixed."""
    with wave.open(io.BytesIO(data), "rb") as w:
        rate = w.getframerate()
        width = w.getsampwidth()
        channels = w.getnchannels()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"unsupported WAV sample width {width}")
    if channels == 1:
        return frames, rate
    s = _samples(frames)
    mono = array("h", (sum(s[i : i + channels]) // channels for i in range(0, len(s), channels)))
    return _to_bytes(mono), rate


def resample_pcm16(pcm16: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear-interpolation resampler (good enough for 8k <-> 16k telephony speech)."""
    if src_rate == dst_rate or not pcm16:
        return pcm16
    s = _samples(pcm16)
    n_out = max(1, int(len(s) * dst_rate / src_rate))
    ratio = src_rate / dst_rate
    out = array("h")
    last = len(s) - 1
    for i in range(n_out):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        a = s[min(j, last)]
        b = s[min(j + 1, last)]
        out.append(int(a + (b - a) * frac))
    return _to_bytes(out)


def clip_to_pcm16(clip: AudioClip) -> tuple[bytes, int] | None:
    """Decode an AudioClip into (PCM16, rate); None if the format isn't raw/wav/mulaw."""
    mime = (clip.mime or "").lower()
    if "wav" in mime or clip.data[:4] == b"RIFF":
        return wav_to_pcm16(clip.data)
    if "mulaw" in mime or "ulaw" in mime or "basic" in mime:
        return ulaw_to_pcm16(clip.data), clip.sample_rate or 8000
    if "l16" in mime or "pcm" in mime or "raw" in mime:
        return clip.data, clip.sample_rate or 16000
    return None


def frame_features(pcm16: bytes, sample_rate: int, frame_ms: int = 20) -> list[tuple[float, float]]:
    """Per-frame (rms, zero_crossing_rate)."""
    s = _samples(pcm16)
    n = max(1, sample_rate * frame_ms // 1000)
    feats: list[tuple[float, float]] = []
    for start in range(0, len(s) - n + 1, n):
        frame = s[start : start + n]
        energy = math.sqrt(sum(x * x for x in frame) / n)
        crossings = sum(1 for a, b in zip(frame, frame[1:], strict=False) if (a < 0) != (b < 0))
        feats.append((energy, crossings / n))
    return feats


def rms(pcm16: bytes) -> float:
    s = _samples(pcm16)
    if not s:
        return 0.0
    return math.sqrt(sum(x * x for x in s) / len(s))


# =============================================================================== synthesis


def tone(
    freqs: float | tuple[float, ...],
    duration_s: float,
    sample_rate: int = 8000,
    amplitude: float = 0.3,
) -> bytes:
    """Sum of sines (PCM16). ``amplitude`` is the total peak as a fraction of full scale."""
    fs = (freqs,) if isinstance(freqs, (int, float)) else tuple(freqs)
    n = int(duration_s * sample_rate)
    peak = 32767 * amplitude / max(1, len(fs))
    out = array(
        "h",
        (
            int(peak * sum(math.sin(2 * math.pi * f * i / sample_rate) for f in fs))
            for i in range(n)
        ),
    )
    return _to_bytes(out)


def silence(duration_s: float, sample_rate: int = 8000) -> bytes:
    return b"\x00\x00" * int(duration_s * sample_rate)


DTMF_FREQS: dict[str, tuple[int, int]] = {
    "1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "A": (697, 1633),
    "4": (770, 1209), "5": (770, 1336), "6": (770, 1477), "B": (770, 1633),
    "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "C": (852, 1633),
    "*": (941, 1209), "0": (941, 1336), "#": (941, 1477), "D": (941, 1633),
}  # fmt: skip


def dtmf_pcm16(digits: str, sample_rate: int = 8000, tone_ms: int = 120, gap_ms: int = 80) -> bytes:
    """In-band DTMF tones. 'w' = 0.5 s pause (Twilio convention)."""
    out = bytearray()
    for ch in digits:
        if ch in (" ", "-"):
            continue
        if ch.lower() == "w":
            out += silence(0.5, sample_rate)
            continue
        f = DTMF_FREQS.get(ch.upper())
        if f is None:
            raise ValueError(f"invalid DTMF digit {ch!r}")
        out += tone(f, tone_ms / 1000, sample_rate, amplitude=0.5)
        out += silence(gap_ms / 1000, sample_rate)
    return bytes(out)


# =============================================================================== Ogg

_OGG_CRC_TABLE: list[int] = []


def _crc_table() -> list[int]:
    if not _OGG_CRC_TABLE:
        for i in range(256):
            r = i << 24
            for _ in range(8):
                r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
            _OGG_CRC_TABLE.append(r & 0xFFFFFFFF)
    return _OGG_CRC_TABLE


def ogg_crc(data: bytes) -> int:
    table = _crc_table()
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ table[((crc >> 24) & 0xFF) ^ b]
    return crc


@dataclass
class OggPage:
    header_type: int
    granule: int
    serial: int
    seq: int
    segments: list[int]
    body: bytes


def iter_ogg_pages(data: bytes):
    pos = 0
    while pos + 27 <= len(data):
        if data[pos : pos + 4] != b"OggS":
            raise ValueError("not an Ogg stream (bad capture pattern)")
        header_type = data[pos + 5]
        granule, serial, seq, _crc = struct.unpack_from("<qIII", data, pos + 6)
        nseg = data[pos + 26]
        segs = list(data[pos + 27 : pos + 27 + nseg])
        body_start = pos + 27 + nseg
        body_len = sum(segs)
        yield OggPage(
            header_type, granule, serial, seq, segs, data[body_start : body_start + body_len]
        )
        pos = body_start + body_len


def ogg_packets(data: bytes) -> tuple[list[bytes], int]:
    """All packets of the (first) logical stream + last granule position."""
    packets: list[bytes] = []
    current = bytearray()
    last_granule = 0
    for page in iter_ogg_pages(data):
        offset = 0
        for seg in page.segments:
            current += page.body[offset : offset + seg]
            offset += seg
            if seg < 255:
                packets.append(bytes(current))
                current = bytearray()
        if page.granule >= 0:
            last_granule = max(last_granule, page.granule)
    if current:
        packets.append(bytes(current))
    return packets, last_granule


def build_ogg(
    packets: list[bytes], *, serial: int = 0x46524459, granules: list[int] | None = None
) -> bytes:
    """One packet per page. Used for fixtures and the simulator's voice notes."""
    out = bytearray()
    for i, pkt in enumerate(packets):
        segs: list[int] = []
        n = len(pkt)
        while n >= 255:
            segs.append(255)
            n -= 255
        segs.append(n)
        header_type = 0x02 if i == 0 else (0x04 if i == len(packets) - 1 else 0)
        granule = granules[i] if granules else 0
        header = bytearray(b"OggS")
        header += bytes([0, header_type])
        header += struct.pack("<qIII", granule, serial, i, 0)
        header += bytes([len(segs)]) + bytes(segs)
        page = bytes(header) + pkt
        crc = ogg_crc(page)
        page = page[:22] + struct.pack("<I", crc) + page[26:]
        out += page
    return bytes(out)


@dataclass
class OpusInfo:
    channels: int = 1
    pre_skip: int = 0
    input_sample_rate: int = 48000
    vendor: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    duration_s: float | None = None


def is_ogg(data: bytes) -> bool:
    return data[:4] == b"OggS"


def parse_opus_ogg(data: bytes) -> OpusInfo:
    """OpusHead + OpusTags (Vorbis comments) + duration from the last granule."""
    packets, last_granule = ogg_packets(data)
    info = OpusInfo()
    if not packets or not packets[0].startswith(b"OpusHead"):
        raise ValueError("not an Ogg/Opus stream")
    head = packets[0]
    info.channels = head[9]
    info.pre_skip = struct.unpack_from("<H", head, 10)[0]
    info.input_sample_rate = struct.unpack_from("<I", head, 12)[0] or 48000
    if len(packets) > 1 and packets[1].startswith(b"OpusTags"):
        tags = packets[1]
        p = 8
        vlen = struct.unpack_from("<I", tags, p)[0]
        p += 4
        info.vendor = tags[p : p + vlen].decode("utf-8", "replace")
        p += vlen
        count = struct.unpack_from("<I", tags, p)[0]
        p += 4
        for _ in range(count):
            clen = struct.unpack_from("<I", tags, p)[0]
            p += 4
            comment = tags[p : p + clen].decode("utf-8", "replace")
            p += clen
            key, _, value = comment.partition("=")
            info.tags[key.upper()] = value
    if last_granule > 0:
        info.duration_s = max(0.0, (last_granule - info.pre_skip) / 48000)
    return info


def build_opus_ogg(
    *, tags: dict[str, str] | None = None, duration_s: float = 1.0, vendor: str = "friday"
) -> bytes:
    """Synthetic Ogg/Opus file (valid container; audio packets are silence stubs)."""
    head = b"OpusHead" + bytes([1, 1]) + struct.pack("<HIhB", 312, 48000, 0, 0)
    comments = [f"{k}={v}".encode() for k, v in (tags or {}).items()]
    vb = vendor.encode()
    body = b"OpusTags" + struct.pack("<I", len(vb)) + vb + struct.pack("<I", len(comments))
    for c in comments:
        body += struct.pack("<I", len(c)) + c
    frames = max(1, int(duration_s / 0.02))
    audio_pkt = bytes([0xF8, 0xFF, 0xFE])  # an Opus "silence" frame (TOC + padding)
    packets = [head, body] + [audio_pkt] * frames
    granules = [0, 0] + [312 + 960 * (i + 1) for i in range(frames)]
    return build_ogg(packets, granules=granules)
