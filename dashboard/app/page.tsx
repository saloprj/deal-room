"use client";
import { useEffect, useState, useCallback } from "react";

type Turn = { speaker: string; text: string; ts: number };
type Call = {
  call_id: string; status: string; transcript: Turn[]; command: string;
  approved: boolean; payment_status: string; checkout_url: string; updated_at: number;
};

const statusPill = (s: string) =>
  s === "live" ? "live" : s === "awaiting_approval" ? "wait" : s === "done" ? "done" : "";

export default function Home() {
  const [call, setCall] = useState<Call | null>(null);
  const [summary, setSummary] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const r = await fetch("/api/state", { cache: "no-store" });
    const j = await r.json();
    setCall(j.call || null);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  const start = async () => { setBusy(true); await fetch("/api/start", { method: "POST" }); await refresh(); setBusy(false); };
  const approve = async () => {
    if (!call) return; setBusy(true);
    await fetch("/api/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ call_id: call.call_id }) });
    await refresh(); setBusy(false);
  };
  const getSummary = async () => { const r = await fetch("/api/summary", { cache: "no-store" }); setSummary((await r.json()).summary); };

  const awaiting = call?.status === "awaiting_approval";

  return (
    <div className="wrap">
      <div className="brand"><span className="dot" /><h1>Deal-Room — Operator Console</h1></div>
      <div className="sub">Autonomous AI sales-call agent · present · translate · research (Exa) · close (Stripe)</div>

      <div className="row">
        <button onClick={start} disabled={busy}>Start call</button>
        <button className="approve" onClick={approve} disabled={busy || !awaiting}>
          {awaiting ? "✓ Approve close (send payment link)" : "Approve close"}
        </button>
        <button className="ghost" onClick={getSummary}>AI summary (via Vercel AI Gateway)</button>
      </div>

      {!call && <div className="card empty">No call yet — click “Start call”.</div>}

      {call && (
        <>
          <div className="card">
            <div className="kv">
              <span className={`pill ${statusPill(call.status)}`}>status: {call.status}</span>
              <span className="pill">{call.call_id}</span>
              <span className={`pill ${call.payment_status === "paid" ? "paid" : ""}`}>payment: {call.payment_status}</span>
              {call.approved && <span className="pill done">approved</span>}
            </div>
            {call.checkout_url && (
              <p style={{ marginTop: 12 }}>💳 <a className="link" href={call.checkout_url} target="_blank">Stripe payment link</a></p>
            )}
          </div>

          {summary && <div className="card"><div className="label">AI summary</div><div className="summary">{summary}</div></div>}

          <div className="card">
            <div className="label">Live transcript</div>
            {(!call.transcript || call.transcript.length === 0) && <div className="empty">Waiting for conversation…</div>}
            {(call.transcript || []).map((t, i) => (
              <div className="turn" key={i}>
                <span className={`who ${t.speaker}`}>{t.speaker}</span>
                <div>{t.text}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
