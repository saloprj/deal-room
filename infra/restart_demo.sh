#!/usr/bin/env bash
# Restart the judge-testable demo host on the EC2 box (run via infra/ssmrun.sh).
#
# Use when sandbox STS creds expire (every few hours) or to redeploy demo_host.py:
#   1. Refresh creds locally, rewrite worker/.env, push it to the box .env
#   2. ./infra/ssmrun.sh i-0dc0b2c261805dbe1 < infra/restart_demo.sh
#
# The demo host owns David's (@dialogbrain) single MTProto session, so the LK
# bridge/agent MUST be stopped first (one voice-call participation per account).
set -e

ENV=/opt/dealroom/worker/.env
[ -f "$ENV" ] || { echo "missing $ENV — push fresh creds first"; exit 1; }

# Free David's session: stop anything else that holds the TG account.
docker stop dealroom-bridge dealroom-interactive 2>/dev/null || true

docker rm -f dealroom-demohost 2>/dev/null || true
docker run -d --restart=unless-stopped --name dealroom-demohost \
  --env-file "$ENV" \
  -e DEAL_PROSPECT_LANG=en \
  -v /opt/media:/media \
  --entrypoint python deal-room-voice:local -u demo_host.py

sleep 8
docker logs dealroom-demohost 2>&1 | tail -15
