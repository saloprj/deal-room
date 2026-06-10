import { NextResponse } from "next/server";
import { registerLead } from "@/lib/ddb";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  try {
    const { username } = await req.json();
    if (!username || typeof username !== "string")
      return NextResponse.json({ error: "username required" }, { status: 400 });
    const u = await registerLead(username);
    return NextResponse.json({ ok: true, username: u });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 400 });
  }
}
