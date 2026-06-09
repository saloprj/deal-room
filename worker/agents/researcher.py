"""Researcher agent — the Deal-Room agent's live senses.

Given a question that needs current information, it queries Exa for fresh,
clean web content and has Bedrock (Claude) synthesize a short, spoken-style
answer with sources. This is the "Best use of Exa" path: Exa is the agent's
real-time grounding during a live call.

Design notes:
- ONE fast Exa query (latency matters mid-call; spec §10).
- Graceful empty/timeout fallback so the call never hangs (spec §5).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from exa_py import Exa

from bedrock_client import BedrockLLM

_FALLBACK = "I don't have a confident answer on that right now — I'll follow up by email with the details."

_SYSTEM = (
    "You are a sales-call assistant answering a prospect's question OUT LOUD on a live call. "
    "Use ONLY the provided web sources. Be concise (2-3 sentences), conversational, and accurate. "
    "If the sources don't cover it, say you'll follow up. Do not invent facts or URLs."
)


@dataclass
class ResearchResult:
    answer: str
    sources: list[dict] = field(default_factory=list)
    ok: bool = True


class Researcher:
    def __init__(self, exa: Exa | None = None, llm: BedrockLLM | None = None):
        self._exa = exa or Exa(os.environ["EXA_API_KEY"])
        self._llm = llm or BedrockLLM()

    def research(self, question: str, *, num_results: int = 4) -> ResearchResult:
        try:
            res = self._exa.search_and_contents(
                question,
                num_results=num_results,
                text={"max_characters": 1200},
                type="auto",
            )
            results = getattr(res, "results", []) or []
        except Exception:
            return ResearchResult(_FALLBACK, ok=False)

        if not results:
            return ResearchResult(_FALLBACK, ok=False)

        sources = [{"title": r.title, "url": r.url} for r in results]
        context = "\n\n".join(
            f"[{i+1}] {r.title}\n{r.url}\n{(r.text or '')[:1000]}" for i, r in enumerate(results)
        )
        prompt = f"Prospect's question: {question}\n\nWeb sources:\n{context}\n\nAnswer out loud now:"
        try:
            answer = self._llm.complete(prompt, system=_SYSTEM, max_tokens=300)
        except Exception:
            return ResearchResult(_FALLBACK, sources=sources, ok=False)
        return ResearchResult(answer, sources=sources, ok=True)
