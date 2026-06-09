"""Deal-Room dispatcher — turns dashboard 'Dispatch agent' clicks into live calls.

Runs on the EC2 box. Polls DynamoDB for calls with status 'dispatch_requested'
(written by the dashboard's /api/dispatch), claims one, and for that chat:

  1. Build a deck for the chat topic   (Exa -> Bedrock)        [AWS]
  2. Render it to a narrated MP4        (Chromium+Polly+ffmpeg) [AWS]
  3. Upload the MP4 to S3 + presign     -> deck_url on the call [AWS]
  4. Join the chat's Telegram voice call and stream the MP4     [pytgcalls]
     while the agent brain (Bedrock) drives transcript + the human-approve gate.

The render/publish steps always run (recordable proof). The live join is
best-effort: if no voice call is joinable, the deck_url + transcript still land
so the dashboard reacts, and the call is marked accordingly (honest status).

Env: TG_API_ID/HASH/SESSION_STRING, DDB_TABLE, DEAL_BUCKET, EXA_API_KEY,
STRIPE_SECRET_KEY, AWS creds/region, DEAL_PROSPECT_LANG.
"""
from __future__ import annotations

import os
import time
import traceback

import boto3

from deck_gen import build_deck
from render_video import build_video
from session import DealRoomSession
from state.store import CallStore

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BUCKET = os.environ.get("DEAL_BUCKET", "deal-room-demo-845532106206")
PLANG = os.environ.get("DEAL_PROSPECT_LANG", "en")
POLL_SEC = 3


def _topic_for(title: str) -> str:
    return (f"DialogBrain — autonomous AI agents that run live multilingual sales "
            f"calls and close deals (pitch for the '{title}' group)")


def _upload_presign(path: str, key: str) -> str:
    s3 = boto3.client("s3", region_name=REGION)
    s3.upload_file(path, BUCKET, key, ExtraArgs={"ContentType": "video/mp4"})
    return s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key},
                                     ExpiresIn=43200)


def render_for(call_id: str, chat_title: str, store: CallStore) -> str:
    """Steps 1-3 — always runs. Returns the presigned deck MP4 url."""
    store.set(call_id, status="presenting")
    store.append_transcript(call_id, "agent", f"Building a tailored deck for {chat_title}…")
    info = build_deck(_topic_for(chat_title), out="deck.html")
    store.append_transcript(call_id, "agent",
                            f"Deck ready: “{info['title']}” ({info['slides']} slides). Rendering narrated video on AWS…")
    vid = build_video("deck.json", "deck.html", out="deck.mp4", lang=PLANG)
    url = _upload_presign("deck.mp4", f"dispatch/{call_id}.mp4")
    store.set(call_id, deck_url=url, status="ready")
    store.append_transcript(call_id, "agent",
                            f"Presentation rendered on AWS ({vid['seconds']}s, Amazon Polly narration). Streaming into the call.")
    return url


def stream_into_call(call_id: str, chat_id: str, store: CallStore) -> None:
    """Step 4 — best-effort live video stream into the chat's voice call."""
    import asyncio

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    async def _go():
        client = TelegramClient(StringSession(os.environ["TG_SESSION_STRING"]),
                                int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
        from pytgcalls import PyTgCalls
        from pytgcalls.types import GroupCallConfig, MediaStream
        await client.start()
        call = PyTgCalls(client)
        await call.start()
        await call.play(int(chat_id), MediaStream("deck.mp4"),
                        config=GroupCallConfig(auto_start=True))
        store.set(call_id, status="live")
        store.append_transcript(call_id, "agent", "Live in the call — presenting now.")
        # Hold while the deck plays; the control poller handles approve/reject.
        await asyncio.sleep(180)
        await client.disconnect()

    asyncio.run(_go())


def handle(item: dict, store: CallStore) -> None:
    cid = item["call_id"]
    chat_id = item.get("chat_id")
    title = item.get("chat_title") or chat_id or cid
    try:
        render_for(cid, title, store)
        if chat_id:
            try:
                stream_into_call(cid, chat_id, store)
            except Exception as e:  # live join is best-effort
                store.set(cid, status="ready", join_error=str(e)[:300])
                store.append_transcript(cid, "agent",
                                        "Couldn't join a live voice call (none active / call busy). "
                                        "The rendered presentation is ready above.")
    except Exception as e:
        store.set(cid, status="error", error=str(e)[:300])
        store.append_transcript(cid, "agent", f"Dispatch failed: {e}")
        traceback.print_exc()


# Per-call brain sessions, kept in-process for multi-turn memory.
_sessions: dict[str, DealRoomSession] = {}


def _session(call_id: str, store: CallStore) -> DealRoomSession:
    s = _sessions.get(call_id)
    if s is None:
        s = DealRoomSession(call_id, store=store, require_approval=True)
        _sessions[call_id] = s
    return s


def answer_questions(items: list[dict], store: CallStore) -> None:
    """Live Q&A — run the agent brain on any call with a pending question."""
    for it in items:
        cid = it["call_id"]
        q = it.get("pending_q")
        if not q:
            continue
        store.set(cid, command="none", pending_q="")  # consume first (idempotent)
        try:
            turn = _session(cid, store).handle(q)  # appends prospect + agent to transcript
            print(f"Q[{cid}] {q!r} -> [{turn.action}] {turn.reply[:80]!r}")
        except Exception as e:
            store.append_transcript(cid, "agent", f"(brain error: {e})")
            traceback.print_exc()


def handle_approvals(items: list[dict], store: CallStore) -> None:
    """Human-in-the-loop: when the operator approves, post the Stripe link."""
    for it in items:
        cid = it["call_id"]
        if it.get("status") == "awaiting_approval" and it.get("approved") and not it.get("link_posted"):
            store.set(cid, link_posted=True)
            _session(cid, store).approve()


def main() -> None:
    store = CallStore()
    ddb = boto3.resource("dynamodb", region_name=REGION).Table(store._table_name)
    print(f"dispatcher up — polling {store._table_name} every {POLL_SEC}s")
    while True:
        try:
            items = [i for i in ddb.scan().get("Items", []) if str(i.get("call_id", "")).startswith("call-")]
            answer_questions(items, store)
            handle_approvals(items, store)
            pend = sorted((i for i in items if i.get("status") == "dispatch_requested"),
                          key=lambda i: i.get("updated_at", 0))
            for it in pend:
                store.set(it["call_id"], status="claimed")  # claim before work
                print(f"dispatch -> {it['call_id']} chat={it.get('chat_id')} ({it.get('chat_title')})")
                handle(it, store)
        except Exception:
            traceback.print_exc()
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
