"use client";
import { useCallback, useEffect, useState } from "react";

type Turn = { speaker: string; text: string; ts: number };
type Call = {
  call_id: string; status: string; transcript: Turn[]; command: string;
  approved: boolean; payment_status: string; checkout_url: string; updated_at: number;
  chat_id?: string; chat_title?: string; deck_url?: string;
};
type Chat = { chat_id: string; title: string; members?: number };

const chipClass = (s: string) =>
  s === "live" ? "live" : s === "awaiting_approval" ? "wait" : s === "done" || s === "closing" ? "done" : "";
const isLive = (s?: string) => !!s && ["live", "awaiting_approval", "closing"].includes(s);

export default function Home() {
  const [call, setCall] = useState<Call | null>(null);
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [nudge, setNudge] = useState("");
  const [chats, setChats] = useState<Chat[]>([]);
  const [dispatching, setDispatching] = useState<string | null>(null);
  const [ask, setAsk] = useState("");
  const [asking, setAsking] = useState(false);

  const refresh = useCallback(async () => {
    const r = await fetch("/api/state", { cache: "no-store" });
    setCall((await r.json()).call || null);
  }, []);
  const loadChats = useCallback(async () => {
    const r = await fetch("/api/chats", { cache: "no-store" });
    setChats((await r.json()).chats || []);
  }, []);
  useEffect(() => { refresh(); const t = setInterval(refresh, 2000); return () => clearInterval(t); }, [refresh]);
  useEffect(() => { loadChats(); const t = setInterval(loadChats, 15000); return () => clearInterval(t); }, [loadChats]);

  const dispatch = async (c: Chat) => {
    setDispatching(c.chat_id);
    await fetch("/api/dispatch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ chat_id: c.chat_id, title: c.title }) });
    await refresh(); setDispatching(null);
  };

  const sendAsk = async () => {
    const q = ask.trim();
    if (!q) return;
    setAsking(true); setAsk("");
    await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ call_id: call?.call_id, text: q }) });
    await refresh(); setAsking(false);
  };

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

      <div className="judges">
        <div className="eyebrow"><span className="bulb" />For judges · test it live in 60 seconds</div>
        <h2>Message <a href="https://t.me/dialogbrain" target="_blank" rel="noreferrer">@dialogbrain</a> on Telegram — the agent runs the whole call itself.</h2>
        <ol className="steps">
          <li><b>DM <a href="https://t.me/dialogbrain" target="_blank" rel="noreferrer">@dialogbrain</a></b> — say hi and ask what it does. It replies and offers a live demo.</li>
          <li><b>Say “yes, show me a demo.”</b> The agent spins up a Telegram group and starts a voice call.</li>
          <li><b>Tap “Join”</b> on the voice chat. It <b>shares its screen</b>, presents the deck, and narrates + advances the slides itself.</li>
          <li><b>Talk between slides</b> — say “next”, “go back”, or ask anything (“what’s the AI agent market size?”). It answers by voice with live Exa research.</li>
          <li><b>Say “I’m ready to pay.”</b> It posts a <b>Stripe</b> checkout link in the chat — test card <span className="mono">4242 4242 4242 4242</span>, any future date / CVC.</li>
        </ol>
        <div className="judges-foot">Runs 100% on AWS (Telegram voice · Amazon Transcribe → Bedrock → Polly · Exa · Stripe). No app install — just Telegram.</div>
      </div>

      <div className="controls">
        <button className="primary" onClick={start} disabled={busy}>◉ Start call</button>
        <button className="ghost" onClick={getSummary} disabled={!call}>✶ AI summary · via Vercel AI Gateway</button>
      </div>

      <div className="card">
        <h3>Chats · dispatch the agent</h3>
        <div className="empty" style={{ marginBottom: 12 }}>
          Telegram groups the agent can join (synced from the worker account). Pick one — the agent joins its voice call and presents.
        </div>
        {!chats.length && <div className="empty">No chats synced yet… (worker publishes them on boot)</div>}
        <div className="chatlist">
          {chats.map((c) => (
            <div className="chatrow" key={c.chat_id}>
              <div className="chatmeta">
                <div className="chatname">{c.title}</div>
                <div className="chatsub">{c.members ? `${c.members} members · ` : ""}{c.chat_id}</div>
              </div>
              <button className="dispatch" onClick={() => dispatch(c)} disabled={dispatching === c.chat_id}>
                {dispatching === c.chat_id ? "Dispatching…" : "▶ Dispatch agent"}
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Talk to the agent · live Q&amp;A</h3>
        <div className="empty" style={{ marginBottom: 10 }}>
          Ask anything a prospect would — pricing, product, “do you support X?”. The agent answers on AWS (Bedrock + live Exa research), and closes via Stripe when you’re ready.
        </div>
        <div className="nudge">
          <input value={ask} onChange={(e) => setAsk(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendAsk()}
            placeholder="e.g. How do you handle multilingual calls? What does it cost?" />
          <button onClick={sendAsk} disabled={asking || !ask.trim()}>{asking ? "Asking…" : "Ask"}</button>
        </div>
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

      {call?.deck_url && (
        <div className="card">
          <h3>Presentation · rendered on AWS</h3>
          <video src={call.deck_url} controls playsInline className="deckvid" />
        </div>
      )}

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
