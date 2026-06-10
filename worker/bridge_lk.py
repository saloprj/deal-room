"""Telegram <-> LiveKit bridge — single event loop (the proven pytgcalls pattern).

pytgcalls' update callbacks (participant joins, inbound stream_frame) do NOT
fire when PyTgCalls runs in a secondary thread/loop — so everything lives on one
asyncio loop, exactly like the working direct worker:

  TG inbound (fork stream_frame, 48k) -> LK AudioSource (SOURCE_MICROPHONE!)
      -> livekit-agent (Silero VAD + Transcribe + Nova Pro + Polly)
  LK agent track -> out_q -> send_frame(MICROPHONE) -> TG

The agent's RoomIO only consumes the linked participant's MICROPHONE-source
track — publishing with default options starves its STT (15s Transcribe death).

Join uses DialogBrain's recovery (full_chat refresh + leave + retry + reconnect).

Env: TG_API_ID/HASH/SESSION_STRING, TG_GROUP_ID, LIVEKIT_URL/API_KEY/API_SECRET,
     LK_ROOM (default unique per run).
"""
from __future__ import annotations

import asyncio
import os
import time

from livekit import api, rtc
from telethon import TelegramClient
from telethon.sessions import StringSession

CHAT = int(os.environ["TG_GROUP_ID"])
LK_URL = os.environ["LIVEKIT_URL"]
LK_KEY = os.environ["LIVEKIT_API_KEY"]
LK_SECRET = os.environ["LIVEKIT_API_SECRET"]
# Fresh room per run so LiveKit auto-dispatches the agent.
ROOM = os.environ.get("LK_ROOM") or f"dealroom-{int(time.time())}"
FRAME_BYTES = 960  # 10ms @ 48k mono s16le
SILENCE = b"\x00" * FRAME_BYTES


async def main():
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
    st = {"self_ssrc": None}
    out_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=800)   # LK agent -> TG
    in_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=800)    # TG -> LK
    stats = {"tg_in": 0, "tg_out": 0}
    frame_info = Frame.Info()
    seen = set()

    # ---------- pytgcalls handlers (must live on THIS loop) ----------
    @call.on_update(fl.call_participant())
    async def _part(_, u: UpdatedGroupCallParticipant):
        if u.participant.user_id == me.id and getattr(u.action, "name", "") == "JOINED":
            st["self_ssrc"] = u.participant.source
            print(f"[tg] self_ssrc={st['self_ssrc']}", flush=True)

    @call.on_update(fl.stream_frame())
    async def _frames(_, u: StreamFrames):
        combo = (getattr(u.direction, "name", ""), getattr(u.device, "name", ""))
        if combo not in seen:
            seen.add(combo)
            print(f"[tg] stream_frame combo {combo}", flush=True)
        for fr in u.frames:
            if st["self_ssrc"] is not None and fr.ssrc == st["self_ssrc"]:
                continue
            try:
                in_q.put_nowait(fr.frame)
                stats["tg_in"] += 1
            except asyncio.QueueFull:
                pass

    # ---------- LiveKit room ----------
    room = rtc.Room()
    src = rtc.AudioSource(48000, 1)
    track = rtc.LocalAudioTrack.create_audio_track("tg-prospect", src)

    async def _consume_agent(atrack: rtc.Track):
        stream = rtc.AudioStream(atrack, sample_rate=48000, num_channels=1)
        print("[lk] consuming agent track -> TG", flush=True)
        async for ev in stream:
            data = bytes(ev.frame.data)
            for i in range(0, len(data), FRAME_BYTES):
                ch = data[i:i + FRAME_BYTES]
                if len(ch) < FRAME_BYTES:
                    ch = ch + b"\x00" * (FRAME_BYTES - len(ch))
                try:
                    out_q.put_nowait(ch)
                    stats["tg_out"] += 1
                except asyncio.QueueFull:
                    pass

    @room.on("track_subscribed")
    def _on_track(atrack, pub, participant):
        if atrack.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.create_task(_consume_agent(atrack))

    token = (api.AccessToken(LK_KEY, LK_SECRET)
             .with_identity("tg-bridge").with_name("TG Bridge")
             .with_grants(api.VideoGrants(room_join=True, room=ROOM,
                                          can_publish=True, can_subscribe=True))
             .to_jwt())
    await room.connect(LK_URL, token)
    # MUST be SOURCE_MICROPHONE — the agent's RoomIO ignores unknown-source
    # tracks, which starves its STT (15s Transcribe death).
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    print(f"[lk] joined room {ROOM} (mic-source track)", flush=True)

    # ---------- robust TG join (DialogBrain recovery) ----------
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

    joined = False
    for attempt in range(1, 13):
        try:
            await call.play(CHAT, MediaStream(media_path=ExternalMedia.AUDIO,
                                              audio_parameters=AudioParameters(48000, 1)),
                            config=GroupCallConfig(auto_start=True))
            await call.record(CHAT, RecordStream(audio=True,
                                                 audio_parameters=AudioParameters(48000, 1)))
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

    # ---------- pumps ----------
    async def _tg_sender():
        loop = asyncio.get_running_loop()
        nt = loop.time()
        while True:
            try:
                ch = out_q.get_nowait()
            except asyncio.QueueEmpty:
                ch = SILENCE
            try:
                await call.send_frame(CHAT, Device.MICROPHONE, ch, frame_info)
            except Exception:
                pass
            nt += 0.01
            d = nt - loop.time()
            await asyncio.sleep(d if d > 0 else 0)

    async def _lk_pump():
        # Continuous 48k into LK (real frames or silence) so the agent's
        # Transcribe never idles out.
        loop = asyncio.get_running_loop()
        nt = loop.time()
        n = 0
        while True:
            try:
                data = in_q.get_nowait()
            except asyncio.QueueEmpty:
                data = SILENCE
            if len(data) != FRAME_BYTES:
                data = (data + SILENCE)[:FRAME_BYTES]
            try:
                await src.capture_frame(rtc.AudioFrame(data, 48000, 1, FRAME_BYTES // 2))
            except Exception:
                pass
            n += 1
            if n % 1000 == 0:
                print(f"[lk] pump={n} tg_in={stats['tg_in']} tg_out={stats['tg_out']}", flush=True)
            nt += 0.01
            d = nt - loop.time()
            await asyncio.sleep(d if d > 0 else 0)

    asyncio.create_task(_tg_sender())
    asyncio.create_task(_lk_pump())
    print("BRIDGE up — TG <-> LiveKit (single loop)", flush=True)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
