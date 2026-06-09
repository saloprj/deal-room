"""One-shot: join a Telegram group voice call and stream a ready MP4 — verbose.

Used for live testing the join path without waiting on a deck render.
Resolves the chat entity first (fresh StringSession has no dialog cache).

Env: TG_API_ID/HASH/SESSION_STRING, TG_GROUP_ID, MEDIA (path to mp4), HOLD (sec).
"""
from __future__ import annotations

import asyncio
import os

from telethon import TelegramClient
from telethon.sessions import StringSession

CHAT = int(os.environ["TG_GROUP_ID"])
MEDIA = os.environ.get("MEDIA", "deck.mp4")
HOLD = int(os.environ.get("HOLD", "180"))
# JOIN an existing call by default (don't create one — creating + leaving ends it
# for everyone). Operator keeps the video chat open; the agent just walks in.
AUTO_START = os.environ.get("AUTO_START", "0") == "1"
LEAVE = os.environ.get("LEAVE", "0") == "1"  # default: don't leave (keep call alive)


async def main():
    client = TelegramClient(StringSession(os.environ["TG_SESSION_STRING"]),
                            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    from pytgcalls import PyTgCalls
    from pytgcalls.types import GroupCallConfig, MediaStream
    await client.start()
    me = await client.get_me()
    print(f"logged in as @{me.username} (id={me.id})", flush=True)
    await client.get_dialogs()  # prime entity cache so pytgcalls can resolve CHAT
    peer = await client.get_entity(CHAT)
    print(f"resolved peer: {getattr(peer, 'title', peer)}", flush=True)
    call = PyTgCalls(client)
    await call.start()
    print(f"joining {'(create-if-needed)' if AUTO_START else '(existing only)'} + streaming {MEDIA} …", flush=True)
    await call.play(CHAT, MediaStream(MEDIA), config=GroupCallConfig(auto_start=AUTO_START))
    print("JOINED — presenting now", flush=True)
    await asyncio.sleep(HOLD)
    if LEAVE:
        await call.leave_call(CHAT)
        print("left call", flush=True)
    else:
        print("done streaming; staying connected (not ending the call)", flush=True)
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
