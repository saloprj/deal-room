import { NextResponse } from "next/server";
import { listChats } from "@/lib/ddb";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json({ chats: await listChats() });
  } catch (e: any) {
    return NextResponse.json({ chats: [], error: String(e?.message || e) }, { status: 500 });
  }
}
