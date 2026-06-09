import { NextResponse } from "next/server";
import { latestCall } from "@/lib/ddb";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const call = await latestCall();
    return NextResponse.json({ call });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 500 });
  }
}
