"""Telegram <-> LiveKit bridge — pipes a TG group call into a LiveKit room.

  TG inbound (fork stream_frame, 48k) --capture_frame--> LK AudioSource
      -> the livekit-agent (VAD + Transcribe + Bedrock + Polly) hears the prospect
  LK agent track --AudioStream--> out_q -> send_frame(MICROPHONE) -> TG
      -> the prospect hears the agent

The agent auto-dispatches into the room when the bridge joins (publishes a track).
VAD turn-detection in the agent is what removes the long STT pauses.

Env: TG_API_ID/HASH/SESSION_STRING, TG_GROUP_ID, LIVEKIT_URL/API_KEY/API_SECRET,
     LK_ROOM (default 'dealroom').
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
# Fresh room per run so LiveKit auto-dispatches the agent (a reused room with a
# prior failed job won't re-dispatch).
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
    print(f"logged in as @{me.username} (id={me.id})", flush=True)
    await client.get_dialogs()
    await client.get_entity(CHAT)

    call = PyTgCalls(client)
    st = {"self_ssrc": None}
    out_q: asyncio.Queue[bytes] = asyncio.Queue()
    frame_info = Frame.Info()

    # --- LiveKit room: publish prospect audio, consume agent audio ---
    room = rtc.Room()
    src = rtc.AudioSource(48000, 1)
    track = rtc.LocalAudioTrack.create_audio_track("tg-prospect", src)

    async def _consume_agent(atrack: rtc.Track):
        # SDK resamples the agent's TTS to 48k mono for us.
        stream = rtc.AudioStream(atrack, sample_rate=48000, num_channels=1)
        print("consuming agent track -> TG", flush=True)
        async for ev in stream:
            data = bytes(ev.frame.data)
            for i in range(0, len(data), FRAME_BYTES):
                ch = data[i:i + FRAME_BYTES]
                if len(ch) < FRAME_BYTES:
                    ch = ch + b"\x00" * (FRAME_BYTES - len(ch))
                out_q.put_nowait(ch)

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
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions())
    print(f"joined LK room {ROOM}", flush=True)

    # --- Telegram call ---
    @call.on_update(fl.call_participant())
    async def _part(_, u: UpdatedGroupCallParticipant):
        if u.participant.user_id == me.id and getattr(u.action, "name", "") == "JOINED":
            st["self_ssrc"] = u.participant.source
            print(f"self_ssrc={st['self_ssrc']}", flush=True)

    in_q: asyncio.Queue[bytes] = asyncio.Queue()
    seen_combos: set = set()

    @call.on_update(fl.stream_frame())
    async def _frames(_, u: StreamFrames):
        combo = (getattr(u.direction, "name", str(u.direction)),
                 getattr(u.device, "name", str(u.device)))
        if combo not in seen_combos:
            seen_combos.add(combo)
            print(f"[bridge] stream_frame combo {combo} ssrcs={[f.ssrc for f in u.frames]} "
                  f"self={st['self_ssrc']}", flush=True)
        for fr in u.frames:
            if st["self_ssrc"] is not None and fr.ssrc == st["self_ssrc"]:
                continue
            try:
                in_q.put_nowait(fr.frame)
            except Exception:
                pass

    async def _lk_pump():
        # Continuous 48k stream into the LK room (real TG frames or silence) so
        # the agent's Transcribe never times out (15s no-audio = session death).
        loop = asyncio.get_running_loop()
        nt = loop.time()
        n = 0
        real = 0
        errs = 0
        while True:
            try:
                data = in_q.get_nowait()
                real += 1
            except asyncio.QueueEmpty:
                data = SILENCE
            if len(data) != FRAME_BYTES:
                data = (data + SILENCE)[:FRAME_BYTES]
            try:
                await src.capture_frame(rtc.AudioFrame(data, 48000, 1, FRAME_BYTES // 2))
            except Exception as e:
                errs += 1
                if errs <= 2:
                    print(f"[lk_pump] capture_frame err: {e}", flush=True)
            n += 1
            if n % 500 == 0:
                print(f"[lk_pump] pushed={n} real_tg={real} errs={errs}", flush=True)
            nt += 0.01
            d = nt - loop.time()
            if d > 0:
                await asyncio.sleep(d)
            else:
                nt = loop.time()

    async def _sender():
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
            if d > 0:
                await asyncio.sleep(d)
            else:
                nt = loop.time()

    await call.start()
    try:
        from ntgcalls import set_log_level
        set_log_level(4)
    except Exception:
        pass
    await call.play(CHAT, MediaStream(media_path=ExternalMedia.AUDIO,
                                      audio_parameters=AudioParameters(48000, 1)),
                    config=GroupCallConfig(auto_start=True))
    await call.record(CHAT, RecordStream(audio=True, audio_parameters=AudioParameters(48000, 1)))
    asyncio.create_task(_sender())     # LK agent audio -> TG
    asyncio.create_task(_lk_pump())    # TG prospect audio -> LK (continuous)
    print("BRIDGE up — TG <-> LiveKit", flush=True)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
