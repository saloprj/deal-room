# Deal-Room 🤝

**An autonomous AI sales agent that runs a live, multilingual sales call end-to-end — it presents, answers, researches, and closes, with a human holding the keys.**

> SuperAI NEXT Hackathon 2026 · Track: Retail Experience Assistants
> Built on **AWS · Vercel · Exa · Stripe**

🔗 **Live demo:** https://dashboard-chi-sepia-54.vercel.app  ·  🎥 **Demo video:** _(link)_

---

## 🧪 Test it live (judges)

The whole flow is self-serve on Telegram — no account setup needed beyond your own Telegram app:

1. **Message [@dialogbrain](https://t.me/dialogbrain)** on Telegram — say you're interested and ask what it does.
2. The agent replies and **offers a live demo call**. Say **"yes"** (or "let's do it").
3. It **creates a group with you and starts a voice call.** Open the call (tap the voice-chat bar at the top of the new group).
4. As soon as you're in, the agent **greets you and presents a short deck** (video + narration), then listens.
5. **Ask it anything by voice** — pricing, how it works, or a research question like *"what's the AI agent market size?"* (it pulls live web facts via Exa).
6. Say **"I'm ready to pay"** → it posts a **Stripe checkout link** in the group chat. It's test mode — pay with card **4242 4242 4242 4242**, any future expiry, any CVC.

Everything above runs on AWS (Telegram voice via pytgcalls, Amazon Transcribe → Bedrock → Polly, Exa research, Stripe close) — one EC2 box, zero external orchestration.

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
