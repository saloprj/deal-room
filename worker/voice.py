"""AWS-native voice helpers for the Deal-Room call worker.

Keeps the whole voice path on AWS (reinforces the "agents run on AWS" gate) and
out of the public repo's proprietary surface:
  - TTS:        Amazon Polly  (text -> 48 kHz mono 16-bit PCM for pytgcalls)
  - Translate:  Amazon Translate (prospect language <-> English)
  - STT:        Amazon Transcribe streaming (wired in call_worker.py)

pytgcalls expects 48 kHz, mono, signed-16 PCM. Polly's max PCM rate is 16 kHz,
so we upsample 16k -> 48k with audioop.ratecv.
"""
from __future__ import annotations

import boto3
import numpy as np

REGION = "us-east-1"
TARGET_RATE = 48000

# Polly neural voices per language (extend as needed).
VOICE = {"en": "Joanna", "ru": "Tatyana", "es": "Lucia", "fr": "Lea", "de": "Vicki"}

_polly = boto3.client("polly", region_name=REGION)
_translate = boto3.client("translate", region_name=REGION)


def synthesize_pcm48k(text: str, lang: str = "en") -> bytes:
    """Return 48 kHz mono s16le PCM for `text` in `lang` (ready for send_frame)."""
    voice = VOICE.get(lang, "Joanna")
    engine = "neural"
    try:
        r = _polly.synthesize_speech(Text=text, OutputFormat="pcm", VoiceId=voice,
                                     SampleRate="16000", Engine=engine)
    except Exception:
        r = _polly.synthesize_speech(Text=text, OutputFormat="pcm", VoiceId=voice, SampleRate="16000")
    pcm16k = r["AudioStream"].read()
    return _upsample_16k_to_48k(pcm16k)


def synthesize_mp3(text: str, lang: str = "en") -> bytes:
    """Return Polly neural MP3 for `text` in `lang` (for the video renderer / ffmpeg)."""
    voice = VOICE.get(lang, "Joanna")
    try:
        r = _polly.synthesize_speech(Text=text, OutputFormat="mp3", VoiceId=voice, Engine="neural")
    except Exception:
        r = _polly.synthesize_speech(Text=text, OutputFormat="mp3", VoiceId=voice)
    return r["AudioStream"].read()


def _upsample_16k_to_48k(pcm16k: bytes) -> bytes:
    """16 kHz -> 48 kHz mono s16le via 3x linear interpolation."""
    s = np.frombuffer(pcm16k, dtype=np.int16)
    if s.size == 0:
        return b""
    xp = np.arange(s.size)
    x = np.arange(0, s.size - 1 + 1e-9, 1 / 3)  # 3x samples
    up = np.interp(x, xp, s).astype(np.int16)
    return up.tobytes()


def translate(text: str, *, source: str, target: str) -> str:
    if source == target or not text.strip():
        return text
    return _translate.translate_text(Text=text, SourceLanguageCode=source,
                                     TargetLanguageCode=target)["TranslatedText"]
