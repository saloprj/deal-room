# Deal-Room call worker — joins a Telegram group voice call and runs the agent.
# Long-lived process (a call exceeds Lambda's 15-min cap) -> ECS Fargate or EC2.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libssl3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium for the deck->video renderer (Playwright manages the binary + deps).
RUN python -m playwright install --with-deps chromium

COPY worker/ .

# Runtime env (inject at deploy): AWS creds + region, TG_API_ID/HASH/SESSION_STRING,
# TG_GROUP_ID, DEAL_PROSPECT_LANG, EXA_API_KEY, STRIPE_SECRET_KEY, DDB_TABLE, BEDROCK_MODEL_ID.
CMD ["python", "call_worker.py"]
