"""Publish the worker account's Telegram group chats to DynamoDB.

The dashboard reads this index (call_id="CHATS#index") to show a dispatch list.
Run on the EC2 box (has the acct256 session). Single-shot or via a loop.

Env: TG_API_ID, TG_API_HASH, TG_SESSION_STRING, DDB_TABLE, AWS creds/region.
"""
from __future__ import annotations

import asyncio
import os
import time

import boto3
from telethon import TelegramClient
from telethon.sessions import StringSession

TABLE = os.environ.get("DDB_TABLE", "dealroom_calls")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
CHATS_KEY = "CHATS#index"


async def collect() -> list[dict]:
    client = TelegramClient(StringSession(os.environ["TG_SESSION_STRING"]),
                            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    await client.start()
    chats: list[dict] = []
    async for d in client.iter_dialogs():
        if not (d.is_group or (d.is_channel and getattr(d.entity, "megagroup", False))):
            continue
        chats.append({
            "chat_id": str(d.id),
            "title": d.name or str(d.id),
            "members": int(getattr(d.entity, "participants_count", 0) or 0),
        })
    await client.disconnect()
    return chats


def publish(chats: list[dict]) -> None:
    ddb = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    ddb.put_item(Item={"call_id": CHATS_KEY, "chats": chats, "updated_at": int(time.time())})


if __name__ == "__main__":
    cs = asyncio.run(collect())
    publish(cs)
    print(f"published {len(cs)} chats:")
    for c in cs:
        print(f"  {c['chat_id']:>16}  {c['title']}  ({c['members']})")
