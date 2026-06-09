"""Call state + control bus on DynamoDB.

Single source of truth shared between the Python call worker and the Vercel
dashboard. The worker writes status/transcript and POLLS `command`/`approved`;
the dashboard reads everything and writes commands (start, approve) + the
Stripe webhook writes `payment_status`. This is the only worker<->dashboard
channel — no inbound networking to the worker (sidesteps Fargate ingress).

Item shape (PK = call_id):
  call_id        S   e.g. "call-2026..."
  status         S   starting|joining|live|awaiting_approval|closing|done|error
  transcript     L   [{speaker, text, ts}]
  command        S   none|start|approve|stop
  approved       BOOL
  payment_status S   none|unpaid|paid
  checkout_url   S
  updated_at     N
"""
from __future__ import annotations

import os
import time

import boto3
from botocore.exceptions import ClientError

TABLE = os.environ.get("DDB_TABLE", "dealroom_calls")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


class CallStore:
    def __init__(self, region: str = REGION, table: str = TABLE):
        self._ddb = boto3.resource("dynamodb", region_name=region)
        self._table_name = table
        self._table = self._ddb.Table(table)

    def ensure_table(self) -> None:
        try:
            self._table.load()
            return
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
        self._ddb.create_table(
            TableName=self._table_name,
            KeySchema=[{"AttributeName": "call_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "call_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        self._ddb.meta.client.get_waiter("table_exists").wait(TableName=self._table_name)

    def create_call(self, call_id: str, **extra) -> dict:
        item = {
            "call_id": call_id,
            "status": "starting",
            "transcript": [],
            "command": "none",
            "approved": False,
            "payment_status": "none",
            "checkout_url": "",
            "updated_at": int(time.time()),
            **extra,
        }
        self._table.put_item(Item=item)
        return item

    def get(self, call_id: str) -> dict | None:
        return self._table.get_item(Key={"call_id": call_id}).get("Item")

    def set(self, call_id: str, **fields) -> None:
        fields["updated_at"] = int(time.time())
        expr = "SET " + ", ".join(f"#{k}=:{k}" for k in fields)
        self._table.update_item(
            Key={"call_id": call_id},
            UpdateExpression=expr,
            ExpressionAttributeNames={f"#{k}": k for k in fields},
            ExpressionAttributeValues={f":{k}": v for k, v in fields.items()},
        )

    def append_transcript(self, call_id: str, speaker: str, text: str) -> None:
        entry = {"speaker": speaker, "text": text, "ts": int(time.time())}
        self._table.update_item(
            Key={"call_id": call_id},
            UpdateExpression="SET transcript = list_append(if_not_exists(transcript, :empty), :e), updated_at = :u",
            ExpressionAttributeValues={":e": [entry], ":empty": [], ":u": int(time.time())},
        )
