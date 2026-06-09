import { NextResponse } from "next/server";
import { addNudge } from "@/lib/ddb";

export const runtime = "nodejs";

export async function POST(req: Request) {
  try {
    const { call_id, text } = await req.json();
    if (!call_id || !text) return NextResponse.json({ error: "call_id and text required" }, { status: 400 });
    await addNudge(call_id, text);
    return NextResponse.json({ ok: true });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 500 });
  }
}
