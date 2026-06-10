# Deal-Room 🤝

**An autonomous AI sales agent that runs a live, multilingual sales call end-to-end — it presents, answers, researches, and closes, with a human holding the keys.**

> SuperAI NEXT Hackathon 2026 · Track: Retail Experience Assistants
> Built on **AWS · Vercel · Exa · Stripe**

🔗 **Live demo:** https://dashboard-chi-sepia-54.vercel.app  ·  🎥 **Demo video:** [watch (82s, narrated)](https://github.com/saloprj/deal-room/raw/main/deck/demo.mp4)

---

## 🧪 Test it live (judges)

Self-serve on Telegram — just register your username first (the agent is opt-in, so it only replies to people who ask for the demo):

1. **Open the [live demo](https://dashboard-chi-sepia-54.vercel.app)** → enter your **Telegram username** in the "unlock the demo" box → **Unlock demo**.
2. **Message [@dialogbrain](https://t.me/dialogbrain)** on Telegram — say hi, then **"yes, show me a demo."**
3. It **creates a group with you and starts a voice call.** Tap the voice-chat bar at the top of the new group to **Join**.
4. The agent **greets you and shares its screen** — presenting the deck, narrating and **advancing the slides itself**.
5. **Talk between slides** — say **"next"**, **"go back"**, or ask anything by voice (e.g. *"what's the AI agent market size?"* → live Exa research).
6. Say **"I'm ready to pay"** → it posts a **Stripe checkout link** in the chat. Test mode — card **4242 4242 4242 4242**, any future expiry, any CVC.

Everything above runs on AWS (Telegram voice via pytgcalls + ntgcalls screen-share, Amazon Transcribe → Bedrock → Polly, Exa research, Stripe close) — one EC2 box, zero external orchestration.

---

## What it does

A prospect just sends a message. From there the agent runs the whole deal **on its own**:

1. **Inbound** — the prospect DMs the agent on Telegram (*"interested in your product"*).
2. **Proposes a live demo** — the agent qualifies, then spins up a Telegram group, adds the prospect, and **starts a voice call**.
3. **Presents live** — on the call it **shares a deck on screen**, narrates each slide, and **advances the slides itself**.
4. **Answers in real time** — it hears the prospect (STT), answers in 1–2 spoken sentences, and pulls **live web facts via Exa** when a question needs them — in the prospect's language.
5. **Closes** — when the prospect is ready, it creates a **Stripe** payment link — but only **after a human operator approves** it in the Control Room. You hold the keys.

One message → presented → answered → closed. Autonomously.

---

## Architecture

```
 Prospect (Telegram)
      │  voice + text
      ▼
 ┌─────────────────────────────┐        ┌────────────────────────────┐
 │  Call runtime (Telegram VC) │        │  Control Room (Vercel)     │
 │  screen-share · STT · TTS   │◀──────▶│  live transcript · approve │
 └──────────────┬──────────────┘  Dynamo│  / reject · nudge · steer  │
                │                  DB bus └────────────────────────────┘
                ▼  reason / act
 ┌──────────────────────────────────────────────────────────┐
 │                       AWS                                  │
 │  Bedrock (Claude) — orchestrator: present/answer/research/close
 │  Transcribe — speech-to-text      Polly — text-to-speech
 │  Translate  — 5-language realtime  DynamoDB — control bus
 └──────────────────────────────────────────────────────────┘
        │ live research              │ close
        ▼                            ▼
       Exa                        Stripe
```

- **Brain:** Amazon **Bedrock** (Claude) orchestrates each turn — decides whether to *present, answer, research, or close*.
- **Voice:** Amazon **Transcribe** (hear) + **Polly** (speak) + **Translate** (multilingual), real-time on the call.
- **Live research:** **Exa** `search_and_contents` for fresh, cited facts mid-call.
- **Close:** **Stripe** Checkout, gated by a human Approve/Reject.
- **Operator surface:** **Vercel** "Control Room" — live transcript, dispatch, Talk-to-the-agent Q&A, and the approval gate, over a **DynamoDB** control bus.

---

## How it maps to the judging criteria

| Criterion | In Deal-Room |
|---|---|
| **Agent overview** | One autonomous agent that runs a full sales call |
| **Autonomy** | Decides present/answer/research/close per turn; sets up the call itself |
| **Tool use** | Bedrock, Transcribe, Polly, Translate, Exa, Stripe, screen-share, vision |
| **Orchestration** | Bedrock orchestrator + DynamoDB control bus + operator console |
| **Human-in-the-loop** | Operator **approves/rejects every close** before the Stripe link is sent |
| **Failure handling** | Call-join retry/recovery, graceful research fallback, the approval safety gate |
| **Demo** | One-message-to-close live flow + interactive Control Room |

---

## Repo layout

- `worker/` — call runtime: Telegram voice (pytgcalls), Bedrock orchestrator (`session.py`, `agents/`), AWS voice glue (`voice.py`, `stt.py`), deck generator (`deck_gen.py`), LiveKit pipeline (`agent_lk.py`, `bridge_lk.py`).
- `dashboard/` — Next.js Control Room on Vercel: chats + dispatch, live transcript, **Talk to the agent**, approve/reject close, presentation player.
- `deck/` — pitch deck generator + output.
- `infra/` — AWS deploy (ECR/EC2) + Dockerfiles.

---

## Running it

**Control Room (Vercel):** the live demo URL above — interact with the agent in-browser (no Telegram needed): ask a prospect question → AWS Bedrock + Exa answer → trigger the Stripe close → approve.

**Call runtime (AWS):** containerized worker (`infra/Dockerfile*`) on EC2 — joins the Telegram voice call and runs the Bedrock-driven present/answer/research/close loop with Polly + Transcribe.

Env: `AWS_*`, `BEDROCK_MODEL_ID`, `EXA_API_KEY`, `STRIPE_SECRET_KEY`, `TG_API_ID/HASH/SESSION_STRING`, `DDB_TABLE`.

---

## Team

**dialogbrain** — Denys Deputatov · Denis Somkin
AWS Account: `845532106206`
