"use client";
import { useCallback, useEffect, useState } from "react";

type Turn = { speaker: string; text: string; ts: number };
type Call = {
  call_id: string; status: string; transcript: Turn[]; command: string;
  approved: boolean; payment_status: string; checkout_url: string; updated_at: number;
};

const chipClass = (s: string) =>
  s === "live" ? "live" : s === "awaiting_approval" ? "wait" : s === "done" || s === "closing" ? "done" : "";
const isLive = (s?: string) => !!s && ["live", "awaiting_approval", "closing"].includes(s);

export default function Home() {
  const [call, setCall] = useState<Call | null>(null);
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [nudge, setNudge] = useState("");

  const refresh = useCallback(async () => {
    const r = await fetch("/api/state", { cache: "no-store" });
    setCall((await r.json()).call || null);
  }, []);
  useEffect(() => { refresh(); const t = setInterval(refresh, 2000); return () => clearInterval(t); }, [refresh]);

  const post = async (url: string, body?: any) => {
    setBusy(true);
    await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    await refresh(); setBusy(false);
  };
  const start = () => post("/api/start");
  const approve = () => call && post("/api/approve", { call_id: call.call_id });
  const reject = () => call && post("/api/reject", { call_id: call.call_id });
  const sendNudge = async () => { if (!call || !nudge.trim()) return; await post("/api/nudge", { call_id: call.call_id, text: nudge.trim() }); setNudge(""); };
  const getSummary = async () => { const r = await fetch("/api/summary", { cache: "no-store" }); setSummary((await r.json()).summary); };

  const awaiting = call?.status === "awaiting_approval";

  return (
    <div className="wrap">
      <div className="top">
        <div className="brandline">
          <span className="kicker">DEAL·ROOM</span>
          <h1>Control<span className="em"> Room</span></h1>
        </div>
        <span className={`live ${isLive(call?.status) ? "on" : ""}`}>
          <span className="bulb" />{isLive(call?.status) ? "ON AIR" : "STANDBY"}
        </span>
      </div>
      <div className="tagline">autonomous sales-call agent · present → translate → research(exa) → close(stripe) · you hold the keys</div>

      <div className="controls">
        <button className="primary" onClick={start} disabled={busy}>◉ Start call</button>
        <button className="ghost" onClick={getSummary} disabled={!call}>✶ AI summary · via Vercel AI Gateway</button>
      </div>

      {awaiting && (
        <div className="decision">
          <div className="eyebrow"><span className="bulb" />Human-in-the-loop · decision required</div>
          <h2>The agent wants to close the deal.</h2>
          <p>It’s ready to send the prospect a Stripe payment link (refundable meeting deposit). Nothing is charged until you approve.</p>
          <div className="acts">
            <button className="approve" onClick={approve} disabled={busy}>✓ Approve &amp; send payment link</button>
            <button className="reject" onClick={reject} disabled={busy}>✕ Reject / hold off</button>
          </div>
        </div>
      )}

      {!call && <div className="card"><div className="empty">No active call. Hit “Start call”, or launch the worker into a Telegram voice chat.</div></div>}

      {call && (
        <div className="grid">
          <div className="card">
            <h3>Live transcript</h3>
            <div className="feed">
              {(!call.transcript || !call.transcript.length) && <div className="empty">awaiting conversation…</div>}
              {(call.transcript || []).map((t, i) => (
                <div className="turn" key={i}>
                  <div className={`who ${t.speaker}`}>{t.speaker}</div>
                  <div className="txt">{t.text}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: "grid", gap: 16 }}>
            <div className="card">
              <h3>Session</h3>
              <div className="chips">
                <span className={`chip ${chipClass(call.status)}`}>● {call.status.replace("_", " ")}</span>
                <span className="chip">{call.call_id}</span>
                <span className={`chip ${call.payment_status === "paid" ? "paid" : ""}`}>payment · {call.payment_status}</span>
                {call.approved && <span className="chip done">approved</span>}
              </div>
              {call.checkout_url && (
                <div className="pay">💳 <a href={call.checkout_url} target="_blank" rel="noreferrer">Stripe payment link</a></div>
              )}
            </div>

            <div className="card">
              <h3>Operator nudge · steer the agent</h3>
              <div className="empty" style={{ marginBottom: 10 }}>Inject a line — the agent will say it on the call (override).</div>
              <div className="nudge">
                <input value={nudge} onChange={(e) => setNudge(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendNudge()}
                  placeholder="e.g. Offer them the 20% launch discount" />
                <button onClick={sendNudge} disabled={busy || !nudge.trim()}>Send</button>
              </div>
            </div>

            {summary && <div className="card"><h3>AI summary</h3><div className="summary">{summary}</div></div>}
          </div>
        </div>
      )}
    </div>
  );
}
