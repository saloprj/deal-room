import { NextResponse } from "next/server";
import { dispatchToChat } from "@/lib/ddb";

export const runtime = "nodejs";

export async function POST(req: Request) {
  try {
    const { chat_id, title } = await req.json();
    if (!chat_id) return NextResponse.json({ error: "chat_id required" }, { status: 400 });
    const call = await dispatchToChat(String(chat_id), String(title || chat_id));
    return NextResponse.json({ ok: true, call });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 500 });
  }
}
