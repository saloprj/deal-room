"""Orchestrator — decides the Deal-Room agent's next move.

Given the prospect's latest utterance (and light context), classify the next
action. The call worker then routes to the Presenter / answer path / Researcher
(Exa) / Closer (Stripe). Reasoning runs on Bedrock.

Actions:
  present        — continue the pitch / advance the deck
  answer         — answer from known product context (no live data needed)
  research       — needs current/external facts -> Researcher (Exa)
  request_close  — prospect is ready to proceed/buy/book -> human approval -> Closer
"""
from __future__ import annotations

from bedrock_client import BedrockLLM

ACTIONS = ("present", "answer", "research", "request_close")

_SYSTEM = (
    "You route an AI sales agent on a live call. Read the prospect's latest message and pick "
    "EXACTLY ONE next action:\n"
    "- present: small talk/greeting or 'tell me more' — continue the pitch.\n"
    "- answer: a question answerable from general product knowledge (no fresh data).\n"
    "- research: needs CURRENT or external facts (latest prices, competitor, news, stats, dates).\n"
    "- request_close: the prospect signals readiness to proceed, buy, book, or pay.\n"
    "Reply with ONLY the action word, nothing else."
)


class Orchestrator:
    def __init__(self, llm: BedrockLLM | None = None):
        self._llm = llm or BedrockLLM()

    def decide(self, latest_utterance: str, *, history: list[str] | None = None) -> str:
        ctx = ("\nRecent: " + " | ".join(history[-3:])) if history else ""
        prompt = f'Prospect said: "{latest_utterance}"{ctx}\nNext action:'
        out = self._llm.complete(prompt, system=_SYSTEM, max_tokens=8).strip().lower()
        for a in ACTIONS:
            if a in out:
                return a
        return "answer"
