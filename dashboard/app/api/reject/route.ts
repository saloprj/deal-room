import { NextResponse } from "next/server";
import { setRejected } from "@/lib/ddb";

export const runtime = "nodejs";

export async function POST(req: Request) {
  try {
    const { call_id } = await req.json();
    if (!call_id) return NextResponse.json({ error: "call_id required" }, { status: 400 });
    await setRejected(call_id);
    return NextResponse.json({ ok: true });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 500 });
  }
}
