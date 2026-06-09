"""Join a Telegram group voice call and present a deck MP4 — looping, never ends.

Resolves the chat entity first (fresh StringSession has no dialog cache), joins
(or creates) the call, and re-plays the deck whenever it finishes so the stream
never ends — which means the agent never auto-leaves and the call stays open.

Env: TG_API_ID/HASH/SESSION_STRING, TG_GROUP_ID, MEDIA (path to mp4),
     AUTO_START (1=create if none, default 1).
"""
from __future__ import annotations

import asyncio
import os

from telethon import TelegramClient
from telethon.sessions import StringSession

CHAT = int(os.environ["TG_GROUP_ID"])
MEDIA = os.environ.get("MEDIA", "deck.mp4")
AUTO_START = os.environ.get("AUTO_START", "1") == "1"


async def main():
    client = TelegramClient(StringSession(os.environ["TG_SESSION_STRING"]),
                            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    from pytgcalls import PyTgCalls, filters as fl
    from pytgcalls.types import GroupCallConfig, MediaStream
    await client.start()
    me = await client.get_me()
    print(f"logged in as @{me.username} (id={me.id})", flush=True)
    await client.get_dialogs()  # prime entity cache so pytgcalls can resolve CHAT
    peer = await client.get_entity(CHAT)
    print(f"resolved peer: {getattr(peer, 'title', peer)}", flush=True)
    call = PyTgCalls(client)

    # When the deck finishes, immediately replay it — the stream never ends, so
    # pytgcalls never auto-leaves and the call stays open indefinitely.
    @call.on_update(fl.stream_end())
    async def _loop(_, __):
        print("deck finished -> replaying (loop)", flush=True)
        await call.play(CHAT, MediaStream(MEDIA), config=GroupCallConfig(auto_start=AUTO_START))

    await call.start()
    print(f"joining {'(create-if-needed)' if AUTO_START else '(existing only)'} + streaming {MEDIA} …", flush=True)
    await call.play(CHAT, MediaStream(MEDIA), config=GroupCallConfig(auto_start=AUTO_START))
    print("JOINED — presenting now (looping, will not end the call)", flush=True)
    while True:  # never leave
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
