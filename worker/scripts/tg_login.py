"""Telethon phone-login helper for the Deal-Room call worker.

Two-step login so a human can paste the code between steps:

  send:            python tg_login.py send   +9715...
  signin <code>:   python tg_login.py signin 12345
  signin w/ 2FA:   python tg_login.py signin 12345 <2fa_password>

Reads TG_API_ID / TG_API_HASH from worker/.env.
Step 1 stashes the intermediate StringSession + phone_code_hash in /tmp so step 2
can reconnect on the SAME auth key and complete sign-in. On success it writes the
authorized StringSession into worker/.env as TG_SESSION_STRING.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

ENV = Path(__file__).resolve().parents[1] / ".env"
STASH = Path("/tmp/dr_tg_login.json")


def _env(key: str) -> str:
    for line in ENV.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} not found in {ENV}")


API_ID = int(_env("TG_API_ID"))
API_HASH = _env("TG_API_HASH")


async def send(phone: str):
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    sent = await client.send_code_request(phone)
    STASH.write_text(json.dumps({
        "phone": phone,
        "phone_code_hash": sent.phone_code_hash,
        "session": client.session.save(),
    }))
    STASH.chmod(0o600)
    await client.disconnect()
    print(f"CODE SENT to {phone} (type={sent.type}). Reply with the code.")


async def signin(code: str, password: str | None):
    data = json.loads(STASH.read_text())
    client = TelegramClient(StringSession(data["session"]), API_ID, API_HASH)
    await client.connect()
    from telethon.errors import SessionPasswordNeededError
    try:
        await client.sign_in(data["phone"], code, phone_code_hash=data["phone_code_hash"])
    except SessionPasswordNeededError:
        if not password:
            raise SystemExit("2FA enabled — rerun: signin <code> <2fa_password>")
        await client.sign_in(password=password)
    me = await client.get_me()
    session_str = client.session.save()
    await client.disconnect()
    # persist into worker/.env
    lines = [l for l in ENV.read_text().splitlines() if not l.startswith("TG_SESSION_STRING=")]
    lines.append(f"TG_SESSION_STRING={session_str}")
    ENV.write_text("\n".join(lines) + "\n")
    STASH.unlink(missing_ok=True)
    print(f"SIGNED IN as @{me.username or me.first_name} (id={me.id}). Session saved to worker/.env")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "send":
        asyncio.run(send(sys.argv[2]))
    elif cmd == "signin":
        code = sys.argv[2]
        pw = sys.argv[3] if len(sys.argv) > 3 else None
        asyncio.run(signin(code, pw))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
