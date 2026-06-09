import { NextResponse } from "next/server";
import { latestCall } from "@/lib/ddb";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Vercel AI Gateway (OpenAI-compatible). Satisfies the "integrate a Vercel
// product" gate: the dashboard routes its LLM call through AI Gateway.
const GATEWAY = "https://ai-gateway.vercel.sh/v1/chat/completions";
const MODEL = process.env.GATEWAY_MODEL || "anthropic/claude-sonnet-4.5";

export async function GET() {
  const call = await latestCall();
  if (!call) return NextResponse.json({ summary: "No active call." });
  const key = process.env.AI_GATEWAY_API_KEY;
  if (!key) return NextResponse.json({ summary: "(AI Gateway key not set)", transcript_turns: call.transcript?.length || 0 });

  const convo = (call.transcript || []).map((t) => `${t.speaker}: ${t.text}`).join("\n");
  try {
    const r = await fetch(GATEWAY, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
      body: JSON.stringify({
        model: MODEL,
        messages: [
          { role: "system", content: "Summarize this sales call in 2 sentences for the operator: where it stands and the next action." },
          { role: "user", content: convo || "(no transcript yet)" },
        ],
        max_tokens: 150,
      }),
    });
    const j = await r.json();
    const summary = j?.choices?.[0]?.message?.content ?? `(gateway error: ${r.status})`;
    return NextResponse.json({ summary });
  } catch (e: any) {
    return NextResponse.json({ summary: `(gateway call failed: ${String(e?.message || e)})` });
  }
}
