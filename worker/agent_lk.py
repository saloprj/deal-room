"""LiveKit voice agent — all AWS, low latency via VAD turn-detection + streaming.

Runs the livekit-agents pipeline:
  Silero VAD (endpointing ~300ms) -> Amazon Transcribe (STT) -> Bedrock (LLM)
  -> Amazon Polly (TTS), all streaming. Joins any room the TG<->LK bridge opens.

Env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, AWS creds/region,
     BEDROCK_MODEL_ID, POLLY_VOICE.
"""
from __future__ import annotations

import os

from livekit import agents
from livekit.agents import Agent, AgentSession
from livekit.plugins import aws, silero

PROMPT = (
    "You are the DialogBrain AI sales agent on a live voice call. DialogBrain is "
    "an autonomous multi-channel platform: AI agents that run sales and support "
    "across chat and voice, translate in real time, and act for the business. "
    "Be warm, concise, and persuasive. Keep answers to 1-2 spoken sentences. "
    "Answer questions about product, pricing, and capabilities; when the prospect "
    "is ready to buy, offer to send a secure payment link."
)


async def entrypoint(ctx: agents.JobContext):
    await ctx.connect()
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=aws.STT(),
        llm=aws.LLM(model=os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")),
        tts=aws.TTS(voice=os.environ.get("POLLY_VOICE", "Joanna")),
    )
    await session.start(room=ctx.room, agent=Agent(instructions=PROMPT))
    await session.generate_reply(
        instructions="Greet the prospect in one short sentence and ask what they'd like to know.")


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
