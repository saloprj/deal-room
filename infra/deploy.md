# Deploying the Deal-Room call worker on AWS

The worker is a long-lived process (holds a Telegram voice call), so it runs on
**ECS Fargate** or an **EC2** instance — never Lambda (15-min cap).

## Build & push image (sandbox ECR)
```bash
AWS_REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com
aws ecr create-repository --repository-name deal-room-worker --region $AWS_REGION || true
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR
docker build -f infra/Dockerfile -t $ECR/deal-room-worker:latest .
docker push $ECR/deal-room-worker:latest
```

## Run it (two options)
**Fargate** — register a task def with the image + env vars; run a task in a
public subnet with a public IP (egress for MTProto/WebRTC UDP). If Fargate
networking blocks the call media, fall back to:

**EC2** — `t3.small`, security group allowing **outbound UDP** (TG voice):
```bash
docker run -d --restart=unless-stopped \
  -e AWS_DEFAULT_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=... -e AWS_SESSION_TOKEN=... \
  -e TG_API_ID=... -e TG_API_HASH=... -e TG_SESSION_STRING=... \
  -e TG_GROUP_ID=-5172634473 -e DEAL_PROSPECT_LANG=ru \
  -e EXA_API_KEY=... -e STRIPE_SECRET_KEY=... -e DDB_TABLE=dealroom_calls \
  $ECR/deal-room-worker:latest
```

## Verify (on-site)
1. Operator starts a voice chat in the test group (worker account must be admin).
2. `docker logs -f` — expect `play() joined` + `self_ssrc` pinned + opening line audible.
3. Prospect speaks (in DEAL_PROSPECT_LANG) → transcript appears in the Vercel
   dashboard → agent answers; on a buy signal the dashboard shows **Approve**.
4. ⚠️ Use a **dedicated** TG account (or pause its channel-sync) — an account
   that is also live-syncing will drop the call ~10s in (one MTProto session).
```
