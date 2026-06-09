#!/usr/bin/env bash
set -euo pipefail
IID="$1"; REGION="${REGION:-us-east-1}"
SF=$(mktemp); cat > "$SF"
PF=$(mktemp)
python3 -c 'import json,sys; json.dump({"commands":[open(sys.argv[1]).read()]}, open(sys.argv[2],"w"))' "$SF" "$PF"
CID=$(aws ssm send-command --region "$REGION" --instance-ids "$IID" \
  --document-name AWS-RunShellScript --parameters "file://$PF" \
  --timeout-seconds 3600 --query 'Command.CommandId' --output text)
ST=Pending
for i in $(seq 1 360); do
  ST=$(aws ssm get-command-invocation --region "$REGION" --command-id "$CID" --instance-id "$IID" --query Status --output text 2>/dev/null || echo Pending)
  case "$ST" in Success|Failed|Cancelled|TimedOut) break;; esac
  sleep 5
done
echo "### STATUS: $ST"
echo "### STDOUT:"; aws ssm get-command-invocation --region "$REGION" --command-id "$CID" --instance-id "$IID" --query StandardOutputContent --output text
ERR=$(aws ssm get-command-invocation --region "$REGION" --command-id "$CID" --instance-id "$IID" --query StandardErrorContent --output text)
[ -n "$ERR" ] && { echo "### STDERR:"; echo "$ERR"; } || true
rm -f "$SF" "$PF"
