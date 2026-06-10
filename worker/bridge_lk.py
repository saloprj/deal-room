"""Telegram <-> LiveKit bridge — pytgcalls isolated in its own thread/loop.

The native pytgcalls(ntgcalls) callback dispatch and LiveKit's rtc FFI starve
each other on a single asyncio loop (symptom: inbound stream_frame never fires).
So pytgcalls runs in a DEDICATED thread with its own event loop; LiveKit runs in
the main loop. They exchange 10ms PCM frames over thread-safe queues:

  TG inbound (tg thread) --tg_in queue--> LK AudioSource (main loop) -> agent
  LK agent track (main loop) --tg_out queue--> send_frame (tg thread) -> TG

Join uses DialogBrain's recovery (full_chat refresh + leave + retry + reconnect).

Env: TG_API_ID/HASH/SESSION_STRING, TG_GROUP_ID, LIVEKIT_URL/API_KEY/API_SECRET,
     LK_ROOM (default unique per run).
"""
from __future__ import annotations

import asyncio
import os
import queue
import threading
import time

from livekit import api, rtc
from telethon import TelegramClient
from telethon.sessions import StringSession

CHAT = int(os.environ["TG_GROUP_ID"])
LK_URL = os.environ["LIVEKIT_URL"]
LK_KEY = os.environ["LIVEKIT_API_KEY"]
LK_SECRET = os.environ["LIVEKIT_API_SECRET"]
ROOM = os.environ.get("LK_ROOM") or f"dealroom-{int(time.time())}"
FRAME_BYTES = 960
SILENCE = b"\x00" * FRAME_BYTES

tg_in: "queue.Queue[bytes]" = queue.Queue(maxsize=400)   # prospect TG audio -> LK
tg_out: "queue.Queue[bytes]" = queue.Queue(maxsize=400)  # LK agent audio -> TG
_stats = {"tg_in": 0, "tg_out": 0}


# ----------------------- pytgcalls thread (own loop) -----------------------
def tg_thread_main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_tg_run())
    except Exception as e:
        print(f"[tg] thread crashed: {e}", flush=True)


async def _tg_run():
    client = TelegramClient(StringSession(os.environ["TG_SESSION_STRING"]),
                            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    from pytgcalls import PyTgCalls, filters as fl
    from pytgcalls.types import (Device, ExternalMedia, Frame, GroupCallConfig,
                                 MediaStream, RecordStream, StreamFrames,
                                 UpdatedGroupCallParticipant)
    from pytgcalls.types.raw import AudioParameters

    await client.start()
    me = await client.get_me()
    print(f"[tg] logged in @{me.username} id={me.id}", flush=True)
    await client.get_dialogs()
    await client.get_entity(CHAT)
    call = PyTgCalls(client)
    self_ssrc = {"v": None}
    frame_info = Frame.Info()
    seen = set()

    @call.on_update(fl.call_participant())
    async def _part(_, u: UpdatedGroupCallParticipant):
        if u.participant.user_id == me.id and getattr(u.action, "name", "") == "JOINED":
            self_ssrc["v"] = u.participant.source
            print(f"[tg] self_ssrc={self_ssrc['v']}", flush=True)

    @call.on_update(fl.stream_frame())
    async def _frames(_, u: StreamFrames):
        combo = (getattr(u.direction, "name", ""), getattr(u.device, "name", ""))
        if combo not in seen:
            seen.add(combo)
            print(f"[tg] stream_frame combo {combo}", flush=True)
        for fr in u.frames:
            if self_ssrc["v"] is not None and fr.ssrc == self_ssrc["v"]:
                continue
            try:
                tg_in.put_nowait(fr.frame)
                _stats["tg_in"] += 1
            except queue.Full:
                pass

    async def _refresh_full_chat():
        try:
            from telethon.tl.functions.messages import GetFullChatRequest
            from telethon.tl.functions.channels import GetFullChannelRequest
            from telethon.tl.types import InputPeerChat, InputPeerChannel, InputChannel
            ip = await asyncio.wait_for(client.get_input_entity(CHAT), timeout=3.0)
            if isinstance(ip, InputPeerChat):
                await asyncio.wait_for(client(GetFullChatRequest(chat_id=ip.chat_id)), timeout=3.0)
            elif isinstance(ip, InputPeerChannel):
                await asyncio.wait_for(client(GetFullChannelRequest(
                    channel=InputChannel(channel_id=ip.channel_id, access_hash=ip.access_hash))), timeout=3.0)
        except Exception as e:
            print(f"[tg] full_chat refresh failed: {e}", flush=True)

    await call.start()
    try:
        from ntgcalls import set_log_level
        set_log_level(4)
    except Exception:
        pass

    # robust join (DialogBrain recovery)
    joined = False
    for attempt in range(1, 13):
        try:
            await call.play(CHAT, MediaStream(media_path=ExternalMedia.AUDIO,
                                              audio_parameters=AudioParameters(48000, 1)),
                            config=GroupCallConfig(auto_start=True))
            await call.record(CHAT, RecordStream(audio=True, audio_parameters=AudioParameters(48000, 1)))
            print(f"[tg] connected on attempt {attempt}", flush=True)
            joined = True
            break
        except Exception as e:
            print(f"[tg] join attempt {attempt} failed: {e}", flush=True)
            try:
                await asyncio.wait_for(call.leave_call(CHAT), timeout=2.0)
            except Exception:
                pass
            await _refresh_full_chat()
            if attempt % 4 == 0:
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=3.0)
                    await asyncio.wait_for(client.connect(), timeout=10.0)
                    await client.get_dialogs()
                    await client.get_entity(CHAT)
                except Exception as ce:
                    print(f"[tg] reconnect failed: {ce}", flush=True)
            await asyncio.sleep(1.5)
    if not joined:
        print("[tg] EXHAUSTED join retries", flush=True)
        return

    async def _tg_sender():
        loop = asyncio.get_event_loop()
        nt = loop.time()
        while True:
            try:
                ch = tg_out.get_nowait()
                _stats["tg_out"] += 1
            except queue.Empty:
                ch = SILENCE
            try:
                await call.send_frame(CHAT, Device.MICROPHONE, ch, frame_info)
            except Exception:
                pass
            nt += 0.01
            d = nt - loop.time()
            await asyncio.sleep(d if d > 0 else 0)

    asyncio.create_task(_tg_sender())
    print("[tg] TG side up (own thread/loop)", flush=True)
    while True:
        await asyncio.sleep(3600)


# ----------------------- LiveKit main loop -----------------------
async def lk_main():
    room = rtc.Room()
    src = rtc.AudioSource(48000, 1)
    track = rtc.LocalAudioTrack.create_audio_track("tg-prospect", src)

    async def _consume(atrack: rtc.Track):
        stream = rtc.AudioStream(atrack, sample_rate=48000, num_channels=1)
        print("[lk] consuming agent track -> TG", flush=True)
        async for ev in stream:
            data = bytes(ev.frame.data)
            for i in range(0, len(data), FRAME_BYTES):
                ch = data[i:i + FRAME_BYTES]
                if len(ch) < FRAME_BYTES:
                    ch = ch + b"\x00" * (FRAME_BYTES - len(ch))
                try:
                    tg_out.put_nowait(ch)
                except queue.Full:
                    pass

    @room.on("track_subscribed")
    def _on_track(atrack, pub, participant):
        if atrack.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.create_task(_consume(atrack))

    token = (api.AccessToken(LK_KEY, LK_SECRET)
             .with_identity("tg-bridge").with_name("TG Bridge")
             .with_grants(api.VideoGrants(room_join=True, room=ROOM,
                                          can_publish=True, can_subscribe=True))
             .to_jwt())
    await room.connect(LK_URL, token)
    # MUST publish as SOURCE_MICROPHONE: the agent's RoomIO only consumes the
    # linked participant's microphone-source track — a default (UNKNOWN) source
    # is ignored, the agent's STT starves, and Transcribe dies at 15s.
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    print(f"[lk] joined room {ROOM} (mic-source track published)", flush=True)

    loop = asyncio.get_event_loop()
    nt = loop.time()
    n = 0
    while True:
        try:
            data = tg_in.get_nowait()
        except queue.Empty:
            data = SILENCE
        if len(data) != FRAME_BYTES:
            data = (data + SILENCE)[:FRAME_BYTES]
        try:
            await src.capture_frame(rtc.AudioFrame(data, 48000, 1, FRAME_BYTES // 2))
        except Exception:
            pass
        n += 1
        if n % 500 == 0:
            print(f"[lk] pump={n} tg_in={_stats['tg_in']} tg_out={_stats['tg_out']}", flush=True)
        nt += 0.01
        d = nt - loop.time()
        await asyncio.sleep(d if d > 0 else 0)


if __name__ == "__main__":
    threading.Thread(target=tg_thread_main, daemon=True).start()
    time.sleep(3)  # let the TG thread start joining
    asyncio.run(lk_main())
