import { NextResponse } from "next/server";
import { askAgent } from "@/lib/ddb";

export const runtime = "nodejs";

export async function POST(req: Request) {
  try {
    const { call_id, text } = await req.json();
    if (!text) return NextResponse.json({ error: "text required" }, { status: 400 });
    const id = await askAgent(call_id || undefined, String(text));
    return NextResponse.json({ ok: true, call_id: id });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 500 });
  }
}
