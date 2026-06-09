# Deal-Room

Autonomous AI agent that runs a live multilingual Telegram sales call: presents a deck, translates in real time, answers with live web research (Exa), and closes with a payment (Stripe) behind a human-approval gate. Deployed on AWS + Vercel.

SuperAI NEXT Hackathon 2026 — Team dialogbrain.

## Structure
- `worker/` — Python call worker (Telegram call, voice, presenter, translator, orchestrator; reasons via AWS Bedrock)
- `dashboard/` — Next.js operator console on Vercel (AI Gateway + AI SDK Workflows; start call, live transcript, approve close)
- `infra/` — AWS deploy (ECS Fargate / EC2)

## Integrations
AWS (Bedrock + compute + DynamoDB) · Vercel (AI Gateway + AI SDK Workflows) · Exa (live research) · Stripe (close).
