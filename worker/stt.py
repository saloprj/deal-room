"""Amazon Transcribe streaming STT for the call worker.

Consumes 16 kHz mono s16le PCM fed from pytgcalls inbound frames and calls
`on_final(text)` for each finalized utterance.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent

REGION = "us-east-1"


class _Handler(TranscriptResultStreamHandler):
    def __init__(self, output_stream, on_final: Callable[[str], Awaitable[None]]):
        super().__init__(output_stream)
        self._on_final = on_final
        self._last_partial_t = None  # ~ when the user stopped producing new words

    async def handle_transcript_event(self, event: TranscriptEvent):
        now = time.time()
        for result in event.transcript.results:
            if result.is_partial:
                self._last_partial_t = now
                continue
            for alt in result.alternatives:
                text = (alt.transcript or "").strip()
                if text:
                    lag = (now - self._last_partial_t) if self._last_partial_t else -1
                    print(f"[lat] stt endpoint_lag={lag:.2f}s final={text[:40]!r}", flush=True)
                    self._last_partial_t = None
                    await self._on_final(text)


class TranscribeStreamer:
    def __init__(self, *, locale: str, on_final: Callable[[str], Awaitable[None]]):
        self.locale = locale
        self.on_final = on_final
        self._q: asyncio.Queue[bytes] = asyncio.Queue()

    def feed(self, pcm16k: bytes) -> None:
        if pcm16k:
            try:
                self._q.put_nowait(pcm16k)
            except asyncio.QueueFull:
                pass

    async def run(self):
        client = TranscribeStreamingClient(region=REGION)
        stream = await client.start_stream_transcription(
            language_code=self.locale,
            media_sample_rate_hz=16000,
            media_encoding="pcm",
        )

        async def _writer():
            while True:
                chunk = await self._q.get()
                await stream.input_stream.send_audio_event(audio_chunk=chunk)

        handler = _Handler(stream.output_stream, self.on_final)
        await asyncio.gather(_writer(), handler.handle_events())
