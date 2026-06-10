# Deal-Room — SuperAI NEXT 2026 submission pack

Everything needed to submit at **forms.superai.com/next-submissions** (due **June 11**).

---

## 1. Form fields (paste-ready)

| Field | Value |
|---|---|
| **Project Name** | `Deal-Room` |
| **Challenge Topic** | `Retail Experience Assistants` *(fallback: Open Track)* |
| **Team Name** | `dialogbrain` |
| **AWS Account ID** | `845532106206` *(confirm in Workshop Studio)* |
| **Team Lead Email** | `info@dextrade.com` *(confirm)* |
| **Team Member 1** | Denys Deputatov — `info@dextrade.com` |
| **Team Member 2** | Denis Somkin — `___@___` *(need email)* |
| **GitHub Repository** | `https://github.com/saloprj/deal-room` |
| **Live Demo URL** | `https://dashboard-chi-sepia-54.vercel.app` |
| **Project Thumbnail** | `deck/thumbnail.png` (1200×630, in repo) |

> **Status:** the SuperAI form is already **pre-filled in the browser** (all fields above). Only two things remain before hitting **Submit**: Denis Somkin's email (Team Member 2) and uploading `deck/thumbnail.png`.

### Project Description — the form caps this at **250 characters**. Use this exact short version:

> Autonomous AI agent that runs a live multilingual sales call end-to-end: presents a deck, answers with live Exa research, and closes via Stripe behind a human-approval gate. AWS Bedrock brain · Polly/Transcribe voice · Vercel Control Room.

*(Longer version below for the DoraHacks BUIDL / README, which have no limit.)*

<details><summary>Long description (no char limit — for DoraHacks/README)</summary>

> Deal-Room is an autonomous AI sales agent that runs a live, multilingual sales call end-to-end — it presents, answers, researches, and closes, with a human holding the keys.
>
> A prospect simply messages the agent on Telegram. The agent qualifies them, proposes a live demo, then autonomously spins up a group, adds the prospect, and starts a voice call. On the call it shares a deck on screen, narrates and advances the slides itself, hears the prospect, and answers their questions in 1–2 spoken sentences — pulling fresh facts via live Exa web research when needed, in the prospect's language. When the prospect is ready to buy, it creates a Stripe payment link — but only after a human operator approves it in the Control Room.
>
> Everything runs on AWS: Amazon Bedrock (Claude) is the reasoning brain that orchestrates each turn (present / answer / research / close); Amazon Transcribe + Polly + Translate power real-time multilingual speech; Exa does live in-call web research; Stripe handles the close; DynamoDB is the operator control bus. A Vercel "Control Room" lets a human watch the live transcript, steer the agent, and approve or reject every close in real time — the human-in-the-loop safety gate on each deal.
>
> Built on AWS · Vercel · Exa · Stripe.

</details>

---

## 2. Demo script (record this — submission video + on-stage fallback)

**Target length: ~2 min.** One continuous thread, one prospect message to a closed deal.

1. **(0:00) Hook** — on screen: a Telegram chat. Type as the prospect: *"Hi, I saw DialogBrain — interested, can you show me?"*
2. **(0:10) Agent proposes + sets up** — agent replies, then *"give me a sec, opening a room"*; a group is created, you're added, a voice chat starts. (Show the agent doing this autonomously.)
3. **(0:25) Join the call** — the agent is presenting: deck on screen, narrating, advancing slides.
4. **(0:50) Ask a question** — speak: *"Do you support WhatsApp and multiple languages?"* → agent answers in voice (cite Exa fact if it triggers research).
5. **(1:15) Buy intent** — *"Okay, how do I get started?"* → agent: *"I'll send a secure link — one moment for approval."*
6. **(1:25) Human-in-the-loop** — cut to the **Control Room**: the **Approve** button → click it.
7. **(1:35) Close** — the Stripe payment link lands in the chat. Show the Stripe checkout page.
8. **(1:50) Close card** — logos: AWS · Vercel · Exa · Stripe. One line: *"Autonomous sales call, end to end. You hold the keys."*

> If the live call is unstable on the day, this recorded clip is the safe artifact — embed it in the README and play it on stage.

---

## 3. Presentation outline (top-5 stage, ~3 min)

1. **Problem** (15s) — sales calls don't scale across languages/time zones.
2. **Solution** (15s) — one autonomous agent runs the whole call.
3. **Architecture** (30s) — the one diagram: AWS brain + voice, Exa, Stripe, Vercel control room.
4. **Live/recorded demo** (90s) — the script above.
5. **Why it wins** (20s) — autonomy + every sponsor (AWS/Vercel/Exa/Stripe) + human-in-the-loop close.
6. **Ask / vision** (10s).

---

## 4. DoraHacks BUIDL (draft — in case it's also required)

- **Name:** Deal-Room
- **Tagline:** Autonomous AI agent that runs a live multilingual sales call — presents, answers, researches, and closes. You hold the keys.
- **Hackathon:** SuperAI NEXT 2026 · Track: Retail Experience Assistants
- **Tech stack:** AWS (Bedrock, Transcribe, Polly, Translate, DynamoDB, EC2) · Exa · Stripe · Vercel · Telegram (pytgcalls)
- **GitHub:** https://github.com/saloprj/deal-room
- **Live demo:** https://dashboard-chi-sepia-54.vercel.app
- **Demo video:** _(link)_
- **Description:** use the long description above.
- **Cover image:** `deck/thumbnail.png`

---

## 5. Pre-submit checklist
- [ ] Repo public, README has demo-video link
- [ ] Live Demo URL works in-browser without Telegram (self-contained, durable creds)
- [ ] Demo video recorded + hosted (YouTube/Loom) + linked in README
- [ ] AWS Account ID confirmed (Workshop Studio)
- [ ] Denis Somkin's email
- [ ] Confirm with organizers: DoraHacks BUIDL also required? Remote-submission OK?
- [ ] Submit form before **June 11**
