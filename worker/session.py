"""DealRoomSession — the agentic core of a Deal-Room call.

Ties the agents together into one decision loop, independent of the audio I/O
(the call worker feeds it transcribed utterances and speaks its replies; this
same engine also drives the text simulation used for testing/demo):

  prospect utterance
     -> Orchestrator.decide  (present | answer | research | request_close)
        -> Presenter narration / Bedrock answer / Researcher(Exa) / Closer(Stripe)
     -> reply (spoken) + state written to DynamoDB (control bus)

Human-in-the-loop: request_close parks at `awaiting_approval`; the operator
approves on the dashboard; only then is the Stripe link posted (approve()).
Failure handling: Researcher returns a graceful fallback on empty/timeout.
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.closer import Closer
from agents.orchestrator import Orchestrator
from agents.researcher import Researcher
from bedrock_client import BedrockLLM
from state.store import CallStore

# Generic pitch context (no tenant-specific data baked in).
PRODUCT_CONTEXT = (
    "You are the AI sales agent for an autonomous multi-channel customer-communication "
    "platform: AI agents that handle sales and support across chat and voice, translate "
    "in real time, and act on behalf of the business. Keep replies short and spoken."
)
DEPOSIT_CENTS = 5000  # $50 refundable deposit to confirm the meeting


@dataclass
class Turn:
    action: str
    reply: str
    sources: list | None = None


class DealRoomSession:
    def __init__(self, call_id: str, *, store=None, orch=None, researcher=None,
                 closer=None, llm=None, require_approval: bool = True):
        self.call_id = call_id
        self.store = store or CallStore()
        self.orch = orch or Orchestrator()
        self.researcher = researcher or Researcher()
        self.closer = closer or Closer()
        self.llm = llm or BedrockLLM()
        self.require_approval = require_approval
        self.history: list[str] = []

    def start(self) -> str:
        self.store.create_call(self.call_id, status="live")
        greeting = "Hi! Thanks for hopping on — I'm the DialogBrain AI agent. Mind if I walk you through what we do?"
        self.store.append_transcript(self.call_id, "agent", greeting)
        return greeting

    def handle(self, utterance: str) -> Turn:
        self.store.append_transcript(self.call_id, "prospect", utterance)
        self.history.append(utterance)
        action = self.orch.decide(utterance, history=self.history)

        if action == "research":
            rr = self.researcher.research(utterance)
            reply, sources = rr.answer, rr.sources
        elif action == "request_close":
            return self._begin_close(utterance)
        elif action == "present":
            reply = self.llm.complete(
                f'Prospect said: "{utterance}". Give the next 2-sentence pitch beat.',
                system=PRODUCT_CONTEXT, max_tokens=160)
            sources = None
        else:  # answer
            reply = self.llm.complete(
                f'Prospect asked: "{utterance}". Answer in 2 sentences.',
                system=PRODUCT_CONTEXT, max_tokens=160)
            sources = None

        self.store.append_transcript(self.call_id, "agent", reply)
        self.store.set(self.call_id, status="live")
        return Turn(action, reply, sources)

    def _begin_close(self, utterance: str) -> Turn:
        co = self.closer.create_checkout(DEPOSIT_CENTS, "DialogBrain — meeting deposit (refundable)")
        if self.require_approval:
            self.store.set(self.call_id, status="awaiting_approval", command="approve",
                           checkout_url=co.url, payment_status="unpaid")
            reply = "Love it. One sec — my colleague will confirm and I'll drop your secure payment link right here."
        else:
            self.store.set(self.call_id, status="closing", checkout_url=co.url, payment_status="unpaid")
            reply = f"Perfect — here's your secure link to lock it in: {co.url}"
        self.store.append_transcript(self.call_id, "agent", reply)
        return Turn("request_close", reply)

    def approve(self) -> str:
        item = self.store.get(self.call_id) or {}
        url = item.get("checkout_url", "")
        self.store.set(self.call_id, status="closing", approved=True)
        reply = f"Approved — here's your secure payment link: {url}"
        self.store.append_transcript(self.call_id, "agent", reply)
        return reply

    def payment_confirmed(self) -> str:
        self.store.set(self.call_id, status="done", payment_status="paid")
        reply = "Payment received — you're all set. Welcome aboard! 🎉"
        self.store.append_transcript(self.call_id, "agent", reply)
        return reply
