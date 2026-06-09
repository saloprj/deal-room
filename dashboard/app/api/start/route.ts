import { NextResponse } from "next/server";
import { createCall } from "@/lib/ddb";

export const runtime = "nodejs";

export async function POST() {
  try {
    const id = `call-${Date.now()}`;
    const item = await createCall(id);
    return NextResponse.json({ ok: true, call: item });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 500 });
  }
}
