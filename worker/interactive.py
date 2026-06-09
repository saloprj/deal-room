"""Interactive in-call agent — hears you and answers, smooth audio, all AWS.

Output: each answer is synthesized by Amazon Polly to a file and PLAYED via
pytgcalls — ntgcalls paces file playback, so it's smooth. (A hand-rolled 10ms
send_frame pump could not hold cadence and produced choppy/laggy speech.)

Input: record() -> stream_frame (INCOMING/MICROPHONE, surfaced by the ntgcalls
fork) -> 48k->16k -> Amazon Transcribe -> DealRoomSession (Bedrock + Exa +
Stripe) -> Polly -> played back in the call.

All blocking AWS calls run off the event loop (to_thread). Transcribe is kept
alive with silence + auto-reconnect so the agent listens continuously.

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
from session import DealRoomSession, PRODUCT_CONTEXT
from stt import TranscribeStreamer

# Explicit buy signals route to the full close flow (Stripe + human approval);
# everything else takes the fast single-LLM-call answer path.
_BUY_SIGNALS = ("buy", "sign up", "sign me up", "let's do it", "lets do it",
                "deposit", "purchase", "take my money", "i'm in", "im in",
                "subscribe", "send me the link", "how do i pay", "let's close")

CHAT = int(os.environ["TG_GROUP_ID"])
PLANG = os.environ.get("DEAL_PROSPECT_LANG", "en")
STT_LOCALE = {"ru": "ru-RU", "en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE"}.get(PLANG, "en-US")
SILENCE16K = b"\x00" * 320  # 10ms @ 16k — keepalive for Transcribe while speaking


def _ds_48_16(pcm: bytes) -> bytes:
    s = np.frombuffer(pcm, dtype=np.int16)
    return s[::3].tobytes() if s.size else b""


def _probe_dur(path: str) -> float:
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=10).stdout.strip()
        return float(out)
    except Exception:
        return 8.0


async def main():
    client = TelegramClient(StringSession(os.environ["TG_SESSION_STRING"]),
                            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    from pytgcalls import PyTgCalls, filters as fl
    from pytgcalls.types import (GroupCallConfig, MediaStream, RecordStream,
                                 StreamFrames, UpdatedGroupCallParticipant)
    from pytgcalls.types.raw import AudioParameters

    await client.start()
    me = await client.get_me()
    print(f"logged in as @{me.username} (id={me.id})", flush=True)
    await client.get_dialogs()
    await client.get_entity(CHAT)

    call = PyTgCalls(client)
    session = DealRoomSession(f"call-incall-{int(time.time())}", require_approval=True)
    st = {"self_ssrc": None, "speaking": False}
    stt: TranscribeStreamer | None = None
    play_done = asyncio.Event()
    seq = {"n": 0}

    @call.on_update(fl.call_participant())
    async def _part(_, u: UpdatedGroupCallParticipant):
        if u.participant.user_id == me.id and getattr(u.action, "name", "") == "JOINED":
            st["self_ssrc"] = u.participant.source
            print(f"self_ssrc={st['self_ssrc']}", flush=True)

    @call.on_update(fl.stream_end())
    async def _end(_, __):
        play_done.set()  # the current answer file finished playing

    seen_combos: set = set()

    @call.on_update(fl.stream_frame())
    async def _frames(_, u: StreamFrames):
        combo = (getattr(u.direction, "name", str(u.direction)),
                 getattr(u.device, "name", str(u.device)))
        if combo not in seen_combos:
            seen_combos.add(combo)
            print(f"stream_frame combo {combo} bytes="
                  f"{len(u.frames[0].frame) if u.frames else 0}", flush=True)
        if stt is None:
            return
        if st["speaking"]:
            stt.feed(SILENCE16K)  # keepalive; ignore our own voice echo
            return
        for fr in u.frames:
            if st["self_ssrc"] is not None and fr.ssrc == st["self_ssrc"]:
                continue
            stt.feed(_ds_48_16(fr.frame))

    async def speak(text: str):
        # Translate + synthesize off-loop (blocking boto3); write to a file and
        # let ntgcalls pace playback (smooth — no manual frame pump).
        say = text
        if PLANG != "en":
            say = await asyncio.to_thread(voice.translate, text, source="en", target=PLANG)
        _t = time.time()
        mp3 = await asyncio.to_thread(voice.synthesize_mp3, say, PLANG)
        tts_ms = (time.time() - _t) * 1000
        seq["n"] += 1
        path = f"/tmp/say_{seq['n']}.mp3"
        with open(path, "wb") as f:
            f.write(mp3)
        dur = await asyncio.to_thread(_probe_dur, path)
        print(f"[lat] tts={tts_ms:.0f}ms dur={dur:.1f}s", flush=True)
        st["speaking"] = True
        try:
            await call.play(CHAT, MediaStream(path), config=GroupCallConfig(auto_start=True))
            # Deterministic wait = actual audio duration (+tail). Don't depend on
            # the stream_end event — a missed event would otherwise hang.
            await asyncio.sleep(dur + 0.5)
        except Exception as e:
            print(f"[speak] play error: {e}", flush=True)
        finally:
            # ALWAYS reopen the ears — a stuck gate makes David permanently deaf.
            st["speaking"] = False
            try:
                os.remove(path)
            except OSError:
                pass

    async def on_utt(text: str):
        if st["speaking"]:
            return
        t0 = time.time()
        print(f"heard: {text!r}", flush=True)
        en = text
        if PLANG != "en":
            en = await asyncio.to_thread(voice.translate, text, source=PLANG, target="en")

        _l = time.time()
        try:
            if any(k in en.lower() for k in _BUY_SIGNALS):
                # Full agentic path (orchestrator -> Stripe close + human approval).
                turn = await asyncio.to_thread(session.handle, en)
                reply = turn.reply
            else:
                # FAST path: one Bedrock call, short spoken reply.
                reply = await asyncio.to_thread(
                    session.llm.complete,
                    f'Prospect said: "{en}". Reply in 1-2 short, natural spoken sentences.',
                    system=PRODUCT_CONTEXT, max_tokens=110)
                asyncio.create_task(asyncio.to_thread(
                    session.store.append_transcript, session.call_id, "prospect", en))
                asyncio.create_task(asyncio.to_thread(
                    session.store.append_transcript, session.call_id, "agent", reply))
        except Exception as e:
            print(f"[lat] llm ERROR after {time.time()-_l:.1f}s: {e}", flush=True)
            reply = "Sorry, could you say that again?"
        print(f"[lat] llm={time.time()-_l:.1f}s think_total={time.time()-t0:.1f}s -> {reply[:70]!r}", flush=True)
        await speak(reply)

    async def _dash_poller():
        """Dashboard 'Talk to the agent' questions -> spoken answer in the call."""
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
    try:
        from ntgcalls import set_log_level
        set_log_level(4)  # 4=NONE — silence verbose WebRTC logs
        print("ntgcalls logging silenced", flush=True)
    except Exception as e:
        print(f"set_log_level unavailable: {e}", flush=True)

    await asyncio.to_thread(session.store.create_call, session.call_id, status="live")
    # First play() joins the call (auto_start) and greets.
    await speak("Hi! I'm the DialogBrain agent. Ask me anything about what we do.")
    # Now register inbound capture and start listening.
    await call.record(CHAT, RecordStream(audio=True, audio_parameters=AudioParameters(48000, 1)))
    if os.environ.get("STT_ENABLED", "1") == "1":
        stt = TranscribeStreamer(locale=STT_LOCALE, on_final=on_utt)

        async def _stt_runner():
            while True:
                try:
                    await stt.run()
                except Exception as e:
                    print(f"stt reconnect: {e}", flush=True)
                await asyncio.sleep(0.3)

        asyncio.create_task(_stt_runner())
    asyncio.create_task(_dash_poller())
    print(f"DASH_CALL_ID={session.call_id}", flush=True)
    print("INTERACTIVE — listening (ask out loud)", flush=True)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
