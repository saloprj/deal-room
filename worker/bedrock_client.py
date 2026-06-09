"""Thin AWS Bedrock (Claude) client — the worker's reasoning path.

Uses the Converse API. Model id from BEDROCK_MODEL_ID (default the global
inference profile that the SuperAI sandbox grants). This is what satisfies the
hackathon's "agents run on an AWS AI endpoint" gate.
"""
from __future__ import annotations

import os

import boto3
from botocore.config import Config

DEFAULT_MODEL = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# Fail fast instead of boto3's 60s default read timeout (a throttle + backoff
# otherwise stalls a whole voice turn for ~1 minute).
_CFG = Config(connect_timeout=5, read_timeout=20,
              retries={"max_attempts": 2, "mode": "standard"})


class BedrockLLM:
    def __init__(self, model_id: str = DEFAULT_MODEL, region: str = "us-east-1"):
        self.model_id = model_id
        self._client = boto3.client("bedrock-runtime", region_name=region, config=_CFG)

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 500) -> str:
        kwargs = {
            "modelId": self.model_id,
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.2},
        }
        if system:
            kwargs["system"] = [{"text": system}]
        resp = self._client.converse(**kwargs)
        return resp["output"]["message"]["content"][0]["text"].strip()
