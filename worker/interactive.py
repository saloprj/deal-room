"""Interactive in-call agent (audio duplex) — hears you and answers, all AWS.

  play(ExternalMedia.AUDIO)  -> outgoing: we push Polly TTS via send_frame  [proven]
  record(RecordStream audio) -> incoming: ntgcalls emits stream_frame       [capture]
    incoming 48k -> 16k -> Amazon Transcribe -> DealRoomSession (Bedrock)
    -> Amazon Polly 48k PCM -> 10ms send_frame cadence -> spoken in the call

Diagnostics: every stream_frame logs direction/device/#frames/bytes so we can
see exactly what the call delivers. Speaking-gate stops the agent transcribing
its own voice.

Env: TG_API_ID/HASH/SESSION_STRING, TG_GROUP_ID, DDB_TABLE, EXA_API_KEY,
     STRIPE_SECRET_KEY, DEAL_PROSPECT_LANG, AWS creds.
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
from stt import TranscribeStreamer

CHAT = int(os.environ["TG_GROUP_ID"])
PLANG = os.environ.get("DEAL_PROSPECT_LANG", "en")
STT_LOCALE = {"ru": "ru-RU", "en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE"}.get(PLANG, "en-US")
FRAME_BYTES = 960  # 10ms @ 48k mono s16le
SILENCE = b"\x00" * FRAME_BYTES
SILENCE16K = b"\x00" * 320  # 10ms @ 16k — keepalive for Transcribe while speaking


def _ds_48_16(pcm: bytes) -> bytes:
    s = np.frombuffer(pcm, dtype=np.int16)
    return s[::3].tobytes() if s.size else b""


async def main():
    client = TelegramClient(StringSession(os.environ["TG_SESSION_STRING"]),
                            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    from pytgcalls import PyTgCalls, filters as fl
    from pytgcalls.types import (Device, ExternalMedia, Frame, GroupCallConfig, MediaStream,
                                 RecordStream, StreamFrames, UpdatedGroupCallParticipant)
    from pytgcalls.types.raw import AudioParameters
    frame_info = Frame.Info()

    await client.start()
    me = await client.get_me()
    print(f"logged in as @{me.username} (id={me.id})", flush=True)
    await client.get_dialogs()
    await client.get_entity(CHAT)

    call = PyTgCalls(client)
    session = DealRoomSession(f"call-incall-{int(time.time())}", require_approval=True)
    st = {"self_ssrc": None, "speaking": False, "fed": 0}
    out_q: asyncio.Queue[bytes] = asyncio.Queue()
    stt: TranscribeStreamer | None = None

    @call.on_update(fl.call_participant())
    async def _part(_, u: UpdatedGroupCallParticipant):
        if u.participant.user_id == me.id and getattr(u.action, "name", "") == "JOINED":
            st["self_ssrc"] = u.participant.source
            print(f"self_ssrc={st['self_ssrc']}", flush=True)

    seen_combos: set = set()

    @call.on_update(fl.stream_frame())
    async def _frames(_, u: StreamFrames):
        # DialogBrain learned the naive INCOMING+SPEAKER filter never matches —
        # discover the real combo at runtime and feed any non-self ssrc.
        combo = (getattr(u.direction, "name", str(u.direction)),
                 getattr(u.device, "name", str(u.device)))
        if combo not in seen_combos:
            seen_combos.add(combo)
            print(f"stream_frame combo dir={combo[0]} dev={combo[1]} ssrcs="
                  f"{[f.ssrc for f in u.frames]} bytes="
                  f"{u.frames[0].frame.__len__() if u.frames else 0}", flush=True)
        if stt is None:
            return
        if st["speaking"]:
            stt.feed(SILENCE16K)  # keepalive: keep Transcribe warm, ignore our echo
            return
        for fr in u.frames:
            if st["self_ssrc"] is not None and fr.ssrc == st["self_ssrc"]:
                continue
            stt.feed(_ds_48_16(fr.frame))
            st["fed"] += 1

    async def _sender():
        # Drift-compensated 10ms cadence: schedule each frame against a fixed
        # clock so time spent in send_frame doesn't slow the stream (which
        # caused stretched/gappy audio with a plain sleep(0.01)).
        loop = asyncio.get_running_loop()
        next_t = loop.time()
        while True:
            try:
                chunk = out_q.get_nowait()
            except asyncio.QueueEmpty:
                chunk = SILENCE
            try:
                await call.send_frame(CHAT, Device.MICROPHONE, chunk, frame_info)
            except Exception:
                pass
            next_t += 0.01
            delay = next_t - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                next_t = loop.time()  # fell behind — resync, don't spiral

    async def speak(text: str):
        # boto3 (Translate/Polly) is BLOCKING — run off the event loop so the
        # 10ms send pump never stalls (that was the mid-utterance hiccup).
        say = text
        if PLANG != "en":
            say = await asyncio.to_thread(voice.translate, text, source="en", target=PLANG)
        pcm = await asyncio.to_thread(voice.synthesize_pcm48k, say, PLANG)
        st["speaking"] = True
        # Enqueue the WHOLE utterance synchronously (no await between frames) so
        # the sender never finds the queue momentarily empty mid-word and pads
        # silence into the middle of a syllable.
        nframes = 0
        for i in range(0, len(pcm), FRAME_BYTES):
            fr = pcm[i:i + FRAME_BYTES]
            if len(fr) < FRAME_BYTES:
                fr = fr + b"\x00" * (FRAME_BYTES - len(fr))
            out_q.put_nowait(fr)
            nframes += 1
        # hold the gate until the queue has actually drained + a small tail.
        while out_q.qsize() > 0:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.6)
        st["speaking"] = False

    async def on_utt(text: str):
        if st["speaking"]:
            return
        print(f"heard: {text!r}", flush=True)
        en = text
        if PLANG != "en":
            en = await asyncio.to_thread(voice.translate, text, source=PLANG, target="en")
        # session.handle does Bedrock + DynamoDB (both blocking) -> off-loop.
        turn = await asyncio.to_thread(session.handle, en)
        print(f"answering [{turn.action}]: {turn.reply[:90]!r}", flush=True)
        await speak(turn.reply)

    async def _dash_poller():
        """Reliable interactive path: questions typed in the dashboard 'Talk to
        the agent' box arrive as pending_q on this call -> the agent speaks the
        answer out loud in the call (uses the proven send_frame output)."""
        while True:
            try:
                item = await asyncio.to_thread(session.store.get, session.call_id) or {}
                q = item.get("pending_q")
                if q and not st["speaking"]:
                    await asyncio.to_thread(session.store.set, session.call_id,
                                            command="none", pending_q="")
                    await on_utt(q)
            except Exception as e:
                print(f"dash_poller err: {e}", flush=True)
            await asyncio.sleep(1.5)

    await call.start()
    # Silence the fork's verbose WebRTC logging (constructor sets LS_INFO). That
    # log flood runs on the event loop and starves the 10ms send pump -> audio
    # hiccups. 0=VERBOSE 1=INFO 2=WARNING 3=ERROR 4=NONE. Must be after start().
    try:
        from ntgcalls import set_log_level
        set_log_level(4)
        print("ntgcalls logging silenced (4=NONE)", flush=True)
    except Exception as e:
        print(f"set_log_level unavailable: {e}", flush=True)
    await call.play(CHAT, MediaStream(media_path=ExternalMedia.AUDIO,
                                      audio_parameters=AudioParameters(48000, 1)),
                    config=GroupCallConfig(auto_start=True))
    await call.record(CHAT, RecordStream(audio=True, audio_parameters=AudioParameters(48000, 1)))
    asyncio.create_task(_sender())
    if os.environ.get("STT_ENABLED", "0") == "1":  # inbound voice capture
        stt = TranscribeStreamer(locale=STT_LOCALE, on_final=on_utt)

        async def _stt_runner():
            # Transcribe streams die after 15s of no audio; auto-reconnect so
            # the agent keeps hearing across the whole call (the "answers once
            # then silent" bug). The keepalive in _frames also feeds silence.
            while True:
                try:
                    await stt.run()
                except Exception as e:
                    print(f"stt reconnect: {e}", flush=True)
                await asyncio.sleep(0.3)

        asyncio.create_task(_stt_runner())
    await asyncio.to_thread(session.store.create_call, session.call_id, status="live")
    asyncio.create_task(_dash_poller())
    print(f"DASH_CALL_ID={session.call_id}", flush=True)
    await speak("Hi! I'm the DialogBrain agent. Ask me anything about what we do.")
    print("INTERACTIVE — listening (ask out loud)", flush=True)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
