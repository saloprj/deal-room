"""Deal-Room voice call worker — the spectacle.

Joins a Telegram group voice call (proven pytgcalls path) and runs the agent
live, fully AWS-native for I/O:

  inbound prospect audio (pytgcalls record + stream_frame)
    -> downsample 48k->16k -> Amazon Transcribe (STT)
    -> Amazon Translate (prospect lang -> English)
    -> DealRoomSession.handle  (Bedrock brain: present/answer/Exa/close)
    -> Amazon Translate (English -> prospect lang)
    -> Amazon Polly (TTS, 48k PCM) -> pytgcalls send_frame (output)

Human-in-the-loop: when the session parks at awaiting_approval, the operator
hits Approve on the Vercel dashboard -> DynamoDB `approved=true` -> the worker
(polling) posts the Stripe link by voice.

Run (inside an env with pytgcalls + amazon-transcribe):
  TG_GROUP_ID=-5172634473 DEAL_PROSPECT_LANG=ru python call_worker.py

Env: TG_API_ID, TG_API_HASH, TG_SESSION_STRING, TG_GROUP_ID, DEAL_PROSPECT_LANG.

NOTE for on-site (Somkin): the OUTPUT path (join + speak) matches the proven
gate_10 probe exactly. The INBOUND frame->STT extraction (ssrc/device) may need
a 1-line tweak after watching real `stream_frame` updates; capture point is
marked CAPTURE below.
"""
from __future__ import annotations

import asyncio
import os
import time

import numpy as np
from telethon import TelegramClient
from telethon.sessions import StringSession

import voice
from session import DealRoomSession

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_SESSION_STRING"]
CHAT_ID = int(os.environ["TG_GROUP_ID"])
PLANG = os.environ.get("DEAL_PROSPECT_LANG", "ru")  # prospect's spoken language
STT_LOCALE = {"ru": "ru-RU", "en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE"}.get(PLANG, "en-US")

FRAME_BYTES = 960          # 10 ms @ 48 kHz mono s16le
SILENCE = b"\x00" * FRAME_BYTES


def _downsample_48k_to_16k(pcm48: bytes) -> bytes:
    s = np.frombuffer(pcm48, dtype=np.int16)
    if s.size == 0:
        return b""
    return s[::3].tobytes()  # 48k -> 16k (decimate by 3)


class VoiceWorker:
    def __init__(self, call_id: str):
        self.call_id = call_id
        self.client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
        from pytgcalls import PyTgCalls
        self.call = PyTgCalls(self.client)
        self.session = DealRoomSession(call_id, require_approval=True)
        self.store = self.session.store
        self.self_ssrc = None
        self.out_q: asyncio.Queue[bytes] = asyncio.Queue()
        self.stt = None  # TranscribeStreamer, set in run()
        self._last_approved = False

    # ---- output: 10 ms send_frame cadence (proven path) ----
    async def _sender(self):
        from pytgcalls.types import Device
        while True:
            try:
                chunk = self.out_q.get_nowait()
            except asyncio.QueueEmpty:
                chunk = SILENCE
            try:
                await self.call.send_frame(CHAT_ID, Device.MICROPHONE, chunk)
            except Exception:
                pass
            await asyncio.sleep(0.01)

    async def speak(self, text_en: str):
        """Translate to prospect language, synthesize, enqueue 10 ms frames."""
        out = voice.translate(text_en, source="en", target=PLANG) if PLANG != "en" else text_en
        pcm = voice.synthesize_pcm48k(out, PLANG)
        for i in range(0, len(pcm), FRAME_BYTES):
            frame = pcm[i:i + FRAME_BYTES]
            if len(frame) < FRAME_BYTES:
                frame = frame + b"\x00" * (FRAME_BYTES - len(frame))
            await self.out_q.put(frame)

    # ---- inbound: prospect speech -> STT -> brain -> speak ----
    async def _on_utterance(self, prospect_text: str):
        en = voice.translate(prospect_text, source=PLANG, target="en") if PLANG != "en" else prospect_text
        self.store.append_transcript(self.call_id, "prospect", prospect_text)
        turn = self.session.handle(en)
        await self.speak(turn.reply)

    async def _approve_poller(self):
        while True:
            item = self.store.get(self.call_id) or {}
            if item.get("status") == "awaiting_approval" and item.get("approved") and not self._last_approved:
                self._last_approved = True
                await self.speak(self.session.approve())
            await asyncio.sleep(1.0)

    async def run(self):
        from pytgcalls import filters as fl
        from pytgcalls.types import (Device, ExternalMedia, GroupCallConfig,
                                     MediaStream, RecordStream, StreamFrames,
                                     UpdatedGroupCallParticipant)
        from pytgcalls.types.raw import AudioParameters

        await self.client.start()

        @self.call.on_update(fl.call_participant())
        async def _on_part(_, u: UpdatedGroupCallParticipant):
            me = await self.client.get_me()
            if u.participant.user_id == me.id and getattr(u.action, "name", "") == "JOINED":
                self.self_ssrc = u.participant.source

        @self.call.on_update(fl.stream_frame())
        async def _on_frames(_, u: StreamFrames):
            for frame in u.frames:
                # CAPTURE: the prospect's audio = any ssrc that isn't ours.
                if self.self_ssrc is not None and frame.ssrc == self.self_ssrc:
                    continue
                if self.stt:
                    self.stt.feed(_downsample_48k_to_16k(frame.frame))

        await self.call.start()
        await self.call.play(
            CHAT_ID,
            MediaStream(media_path=ExternalMedia.AUDIO,
                        audio_parameters=AudioParameters(bitrate=48000, channels=1)),
            config=GroupCallConfig(auto_start=True),
        )
        await self.call.record(
            CHAT_ID,
            RecordStream(audio=True, audio_parameters=AudioParameters(bitrate=48000, channels=1)),
        )

        from stt import TranscribeStreamer  # local import; needs amazon-transcribe
        self.stt = TranscribeStreamer(locale=STT_LOCALE, on_final=self._on_utterance)
        asyncio.create_task(self._sender())
        asyncio.create_task(self._approve_poller())
        asyncio.create_task(self.stt.run())

        await self.speak(self.session.start())  # opening line
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    cid = f"call-{int(time.time())}"
    asyncio.run(VoiceWorker(cid).run())
