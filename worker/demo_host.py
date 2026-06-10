"""Judge-testable demo host — one process, David's single Telegram session.

Flow (all AWS, zero DialogBrain):
  1. Judge DMs @dialogbrain  -> DM brain (Nova Pro) replies, offers a live demo
  2. Judge agrees            -> brain emits 'DEMO_START' -> create a group with the
                                judge, post a "join the call" message, open a voice call
  3. Judge joins the call    -> agent greets, then auto-presents the deck (video+
                                narration), then answers questions by voice
  4. Judge is ready to pay    -> agent creates a Stripe checkout link, posts it in the
                                group chat, and says "the link is in the chat"

Voice engine is the PROVEN direct path (interactive.py): the ntgcalls fork surfaces
inbound INCOMING/MICROPHONE frames -> 48k->16k -> Amazon Transcribe -> Bedrock
(Nova Pro fast path / Sonnet close) -> Amazon Polly -> played back via pytgcalls.

One demo at a time (one account can hold one group voice call). pytgcalls update
handlers are registered once on the shared call object and routed to the active
DemoSession.

Env: TG_API_ID/HASH/SESSION_STRING, EXA_API_KEY, STRIPE_SECRET_KEY, DDB_TABLE,
     DEAL_PROSPECT_LANG, DECK_MEDIA (default /media/deck.mp4), AWS creds.
"""
from __future__ import annotations

import asyncio
import os
import time

import numpy as np
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.tl.functions.messages import CreateChatRequest

import json

import voice
from bedrock_client import BedrockLLM
from session import DealRoomSession, PRODUCT_CONTEXT
from stt import TranscribeStreamer
from agents.closer import Closer
from present_browser import LivePresenter

DECK_PATH = os.environ.get("DECK_MEDIA", "/media/deck.mp4")
DECK_HTML = os.environ.get("DECK_HTML", "/media/deck.html")
DECK_JSON = os.environ.get("DECK_JSON", "/media/deck.json")
SILENCE_MEDIA = os.environ.get("SILENCE_MEDIA", "/media/silence.mp3")
# "live" = browser screen-share + agent-driven slide walk; "video" = baked deck.mp4.
PRESENTER_MODE = os.environ.get("PRESENTER_MODE", "live")
PLANG = os.environ.get("DEAL_PROSPECT_LANG", "en")
STT_LOCALE = {"ru": "ru-RU", "en": "en-US", "es": "es-ES",
              "fr": "fr-FR", "de": "de-DE"}.get(PLANG, "en-US")
SILENCE16K = b"\x00" * 320  # 10ms @ 16k — Transcribe keepalive
FRAME_BYTES_OUT = 960       # 10ms @ 48k mono s16le — external mic send_frame
SILENCE960 = b"\x00" * FRAME_BYTES_OUT
FAST_MODEL = os.environ.get("BEDROCK_FAST_MODEL", "us.amazon.nova-pro-v1:0")

DEAL_AMOUNT_CENTS = int(os.environ.get("DEAL_AMOUNT_CENTS", "5000"))
DEAL_DESCRIPTION = os.environ.get("DEAL_DESCRIPTION", "DialogBrain — onboarding deposit")

_FILLERS = {"oh", "uh", "um", "hmm", "mhm", "huh", "ah", "er", "uh-huh", "mm"}
_BUY_SIGNALS = ("buy", "sign up", "sign me up", "let's do it", "lets do it",
                "deposit", "purchase", "take my money", "i'm in", "im in",
                "subscribe", "send me the link", "send the link", "how do i pay",
                "ready to pay", "i'll pay", "ill pay", "let's close", "pay now",
                "payment", "to pay", "want to pay", "let's pay", "lets pay",
                "checkout", "the link", "send link", "go to payment")
# Stop the auto-walk and move to Q&A / closing.
_STOP_WALK = ("stop", "end presentation", "end the presentation", "that's enough",
              "thats enough", "skip the rest", "finish", "wrap up", "i'm done",
              "im done", "that's all", "enough")
_PRESENT_SIGNALS = ("presentation", "present the deck", "show me the deck",
                    "show the deck", "show slides", "show me slides", "the slides",
                    "walk me through the deck", "show me a demo", "see the deck")
# Voice slide-navigation intents (only meaningful once a live deck is up).
_NAV_NEXT = ("next", "next slide", "go on", "continue", "move on", "keep going",
             "skip ahead", "go forward")
_NAV_BACK = ("back", "go back", "previous", "previous slide", "last slide",
             "the slide before", "one back")

# DM sales brain: chat-mode persuasion that can trigger the live demo. It emits a
# 'DEMO_START' marker on its own line the moment the prospect agrees to a call.
_DM_SYS = (
    PRODUCT_CONTEXT
    + " You are chatting by text with a prospect who messaged us. Be warm, concise "
      "(1-3 sentences), and persuasive. Early on, offer a live voice demo: you can "
      "spin up a call and walk them through a short deck, then answer questions. "
      "When the prospect agrees to a live demo / call (e.g. 'yes', 'sure', 'let's "
      "do it', 'ok'), reply with a one-line confirmation AND put the exact token "
      "DEMO_START on its own final line. Only emit DEMO_START once they have agreed."
)
# Fast in-call voice brain: answer directly, or request Exa research via 'RESEARCH:'.
_FAST_SYS = (
    PRODUCT_CONTEXT
    + " If (and ONLY if) answering well requires fresh web facts — market sizes, news, "
      "competitors, anything you may not know — reply with EXACTLY 'RESEARCH: <web search "
      "query>' and nothing else. Otherwise answer the prospect in 1-2 short, natural "
      "spoken sentences."
)


def _ds_48_16(pcm: bytes) -> bytes:
    s = np.frombuffer(pcm, dtype=np.int16)
    return s[::3].tobytes() if s.size else b""


def _probe_dur(path: str) -> float:
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=10).stdout.strip()
        return float(out)
    except Exception:
        return 8.0


def _exa_search(q: str) -> str:
    from exa_py import Exa
    res = Exa(os.environ["EXA_API_KEY"]).search_and_contents(
        q, num_results=3, text={"max_characters": 600}, type="auto")
    return "\n".join(f"[{i+1}] {r.title}: {(r.text or '')[:500]}"
                     for i, r in enumerate(res.results or []))


class DemoSession:
    """One live demo bound to a freshly created group chat (chat_id)."""

    def __init__(self, host: "DemoHost", chat_id: int):
        self.host = host
        self.client = host.client
        self.call = host.call
        self.me = host.me
        self.chat_id = chat_id
        self.session = DealRoomSession(f"demo-{chat_id}-{int(time.time())}", require_approval=False)
        self.fast_llm = host.fast_llm
        self.closer = host.closer
        self.st = {"self_ssrc": None, "speaking": False, "last_fed": 0.0}
        self.stt: TranscribeStreamer | None = None
        self.presented = False
        self.presenting = False
        self._barge = False
        self.done = False
        self._tasks: list[asyncio.Task] = []
        # Live screen-share presenter (browser) + external-audio plumbing.
        self.presenter: LivePresenter | None = None
        self.external_audio = False
        self.out_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1500)
        self._audio_pump_task: asyncio.Task | None = None
        self._narr: list[str] = []

    # ---- pytgcalls events (routed here by the host) ----
    def on_self_join(self, ssrc):
        self.st["self_ssrc"] = ssrc
        print(f"[demo {self.chat_id}] self_ssrc={ssrc}", flush=True)

    async def on_participant_join(self, user_id):
        # The prospect (anyone who isn't David) joined the voice chat -> open.
        if user_id == self.me.id or self.presented:
            return
        self.presented = True
        print(f"[demo {self.chat_id}] prospect {user_id} joined -> greet + present", flush=True)
        await self._run_presentation()

    async def _run_presentation(self):
        await self.speak("Hi! Thanks for joining. I'm the DialogBrain agent — let me give "
                         "you a quick walkthrough, and feel free to jump in any time.")
        await self.present()
        if not self._barge:
            await self.speak("That's the overview. Ask me anything — pricing, how it works, "
                             "or say you're ready and I'll send a secure payment link.")

    def on_frames(self, frames):
        if self.stt is None:
            return
        if self.st["speaking"]:
            self.stt.feed(SILENCE16K)
            self.st["last_fed"] = time.time()
            return
        for fr in frames:
            if self.st["self_ssrc"] is not None and fr.ssrc == self.st["self_ssrc"]:
                continue
            self.stt.feed(_ds_48_16(fr.frame))
            self.st["last_fed"] = time.time()

    # ---- audio out ----
    async def speak(self, text: str):
        if not text:
            return
        say = text
        if PLANG != "en":
            say = await asyncio.to_thread(voice.translate, text, source="en", target=PLANG)
        if self.external_audio:
            await self._speak_external(say)
        else:
            await self._speak_file(say)

    async def _speak_file(self, say: str):
        """Smooth path (pre-presentation): Polly MP3 -> ntgcalls paces play(file)."""
        from pytgcalls.types import GroupCallConfig, MediaStream
        mp3 = await asyncio.to_thread(voice.synthesize_mp3, say, PLANG)
        path = f"/tmp/say_{self.chat_id}_{int(time.time()*1000)}.mp3"
        with open(path, "wb") as f:
            f.write(mp3)
        dur = await asyncio.to_thread(_probe_dur, path)
        self.st["speaking"] = True
        try:
            for attempt in range(8):
                try:
                    await self.call.play(self.chat_id, MediaStream(path),
                                         config=GroupCallConfig(auto_start=True))
                    break
                except Exception as e:
                    if attempt < 7 and ("not found" in str(e).lower() or "connection" in str(e).lower()):
                        await asyncio.sleep(1.2)
                        continue
                    raise
            await asyncio.sleep(dur + 0.5)
        except Exception as e:
            print(f"[demo {self.chat_id}] speak error: {e}", flush=True)
        finally:
            self.st["speaking"] = False
            try:
                os.remove(path)
            except OSError:
                pass

    async def _speak_external(self, say: str):
        """Presentation path: Polly PCM -> external mic queue (screen-share stays up).

        Listen-through-narration when we know our own ssrc (barge-in); otherwise gate
        STT deaf while we talk so we don't transcribe our own voice."""
        pcm = await asyncio.to_thread(voice.synthesize_pcm48k, say, PLANG)
        # Always deaf while we narrate: the SFU re-mixes our own voice back under a
        # different ssrc than self_ssrc, so it leaks past the filter and gets
        # transcribed as junk fragments ('I', 'um') that drown the prospect's
        # commands. We listen in the gaps between slides instead.
        self.st["speaking"] = True
        try:
            for i in range(0, len(pcm), FRAME_BYTES_OUT):
                if self.done or self._barge:
                    break
                ch = pcm[i:i + FRAME_BYTES_OUT]
                if len(ch) < FRAME_BYTES_OUT:
                    ch = ch + b"\x00" * (FRAME_BYTES_OUT - len(ch))
                await self.out_q.put(ch)            # bounded queue -> backpressure paces us
            # Drain (pump empties at 10ms/frame) unless interrupted.
            while not self.out_q.empty() and not self.done and not self._barge:
                await asyncio.sleep(0.05)
        finally:
            self.st["speaking"] = False
            if self._barge:
                self._flush_audio()

    def _flush_audio(self):
        try:
            while True:
                self.out_q.get_nowait()
        except asyncio.QueueEmpty:
            pass

    async def _audio_pump(self):
        """Continuous 10ms external mic send (narration frames or silence keepalive)."""
        from pytgcalls.types import Device, Frame
        info = Frame.Info()
        loop = asyncio.get_running_loop()
        nt = loop.time()
        while not self.done:
            try:
                ch = self.out_q.get_nowait()
            except asyncio.QueueEmpty:
                ch = SILENCE960
            try:
                await self.call.send_frame(self.chat_id, Device.MICROPHONE, ch, info)
            except Exception:
                pass
            nt += 0.01
            d = nt - loop.time()
            await asyncio.sleep(d if d > 0 else 0)

    # ---- presentation ----
    def _load_narration(self, total: int) -> list[str]:
        """Per-slide narration: reveal slide 0 = title intro, 1..N = deck.json slides."""
        try:
            deck = json.load(open(DECK_JSON))
        except Exception as e:
            print(f"[demo {self.chat_id}] deck.json read err: {e}", flush=True)
            return ["" for _ in range(total)]
        intro = f"{deck.get('title', '')}. {deck.get('subtitle', '')}".strip(". ")
        narr = [intro or "Let me walk you through this."]
        for s in deck.get("slides", []):
            narr.append(s.get("narration") or s.get("heading", ""))
        while len(narr) < total:
            narr.append("")
        return narr[:total]

    def _narr_for(self, idx: int) -> str:
        if 0 <= idx < len(self._narr):
            return self._narr[idx]
        return ""

    async def _go_external(self):
        """Register a Stream(mic=EXTERNAL, screen=EXTERNAL) so screen-share + live
        narration coexist, and start the continuous external-mic pump."""
        if self.external_audio:
            return
        from pytgcalls.types.raw.stream import Stream
        from pytgcalls.types.raw.audio_stream import AudioStream
        from pytgcalls.types.raw.video_stream import VideoStream
        from pytgcalls.types.raw import AudioParameters, VideoParameters
        from pytgcalls.types import GroupCallConfig
        import ntgcalls
        p = self.presenter
        stream = Stream(
            microphone=AudioStream(ntgcalls.MediaSource.EXTERNAL, "", AudioParameters(48000, 1)),
            screen=VideoStream(ntgcalls.MediaSource.EXTERNAL, "",
                               VideoParameters(p.w, p.h, p.fps)),
        )
        await self.call.play(self.chat_id, stream, GroupCallConfig(auto_start=True))
        self.external_audio = True
        self._audio_pump_task = asyncio.create_task(self._audio_pump())
        await asyncio.sleep(0.3)
        print(f"[demo {self.chat_id}] external stream registered (mic+screen)", flush=True)

    async def _listen_gap(self, secs: float):
        t = 0.0
        while t < secs and not self._barge and not self.done:
            await asyncio.sleep(0.2)
            t += 0.2

    async def present(self):
        if PRESENTER_MODE == "live" and os.path.exists(DECK_HTML):
            try:
                return await self._present_live()
            except Exception as e:
                print(f"[demo {self.chat_id}] live present failed -> deck.mp4: {e}", flush=True)
        return await self._present_video()

    async def _present_live(self):
        """Browser screen-share + agent-driven slide walk (narrate -> advance)."""
        if self.presenter is None:
            self.presenter = LivePresenter()
            await self.presenter.launch()
        await self._go_external()
        self.presenter.start_video_pump(self.call, self.chat_id)
        total = await self.presenter.total()
        if total <= 0:
            total = 1
        self._narr = self._load_narration(total)
        print(f"[demo {self.chat_id}] live walk: {total} slides", flush=True)
        self.presenting = True
        self._barge = False
        try:
            for i in range(total):
                if self.done or self._barge:
                    break
                await self.presenter.goto(i)
                await asyncio.sleep(0.5)          # let the slide render before narrating
                await self.speak(self._narr_for(i))
                if self.done or self._barge:
                    break
                await self._listen_gap(2.5)        # window to say next/back/stop/pay
        finally:
            self.presenting = False
        # Screen-share stays live for Q&A; the prospect drives nav by voice now.

    async def _present_video(self):
        from pytgcalls.types import GroupCallConfig, MediaStream
        if not os.path.exists(DECK_PATH):
            print(f"[demo {self.chat_id}] deck missing at {DECK_PATH}", flush=True)
            return
        dur = await asyncio.to_thread(_probe_dur, DECK_PATH)
        # If we know our own ssrc we can filter our deck audio and KEEP LISTENING
        # during the deck -> the prospect can barge in any time. If we don't, stay
        # deaf (so we don't transcribe our own narration) but cap the deaf window.
        listen = self.st.get("self_ssrc") is not None
        cap = dur + 0.5 if listen else min(dur, 40.0)
        print(f"[demo {self.chat_id}] streaming deck (barge-in={'on' if listen else 'off'}, "
              f"cap={cap:.0f}s)", flush=True)
        self.presenting = True
        self._barge = False
        self.st["speaking"] = not listen
        try:
            await self.call.play(self.chat_id, MediaStream(DECK_PATH),
                                 config=GroupCallConfig(auto_start=True))
            elapsed = 0.0
            while elapsed < cap and not self._barge and not self.done:
                await asyncio.sleep(0.3)
                elapsed += 0.3
        except Exception as e:
            print(f"[demo {self.chat_id}] present error: {e}", flush=True)
        finally:
            self.st["speaking"] = False
            self.presenting = False
            if self._barge:
                # Cut the deck so the answer can play immediately.
                print(f"[demo {self.chat_id}] barge-in -> stopping deck", flush=True)
                try:
                    await self.call.play(self.chat_id, MediaStream(SILENCE_MEDIA),
                                         config=GroupCallConfig(auto_start=True))
                except Exception:
                    pass

    async def send_payment_link(self):
        """Create a Stripe checkout link and post it into the group chat."""
        try:
            co = await asyncio.to_thread(
                self.closer.create_checkout, DEAL_AMOUNT_CENTS, DEAL_DESCRIPTION)
        except Exception as e:
            print(f"[demo {self.chat_id}] stripe error: {e}", flush=True)
            await self.speak("I hit a snag creating the link — let me try again in a moment.")
            return
        amount = f"${DEAL_AMOUNT_CENTS/100:.0f}"
        msg = (f"Here's your secure checkout (Stripe, test mode) for {amount}:\n{co.url}\n\n"
               "Test card: 4242 4242 4242 4242, any future date, any CVC.")
        try:
            await self.client.send_message(self.chat_id, msg)
            print(f"[demo {self.chat_id}] stripe link sent: {co.url}", flush=True)
        except Exception as e:
            print(f"[demo {self.chat_id}] link send FAILED: {e}", flush=True)
        try:
            await asyncio.to_thread(self.session.store.set, self.session.call_id,
                                    status="closing", checkout_url=co.url, payment_status="unpaid")
        except Exception:
            pass
        await self.speak("Done — the secure payment link is in the chat. "
                         "It's Stripe test mode, so use card four two four two, four times.")

    # ---- inbound utterance handling ----
    async def on_utt(self, text: str):
        if self.st["speaking"] or self.done:
            return
        print(f"[demo {self.chat_id}] heard: {text!r}", flush=True)
        en = text
        if PLANG != "en":
            en = await asyncio.to_thread(voice.translate, text, source=PLANG, target="en")
        low = en.lower()
        norm = low.strip().strip(".,!?… ")
        if norm in _FILLERS or len(norm) < 3:
            return

        # Robust trigger: if the JOINED event was missed (the call flapped) but we can
        # clearly hear the prospect, kick off greet + presentation now.
        if not self.presented and not self.done:
            self.presented = True
            print(f"[demo {self.chat_id}] heard prospect -> greet + present", flush=True)
            asyncio.create_task(self._run_presentation())
            return

        # Barge-in: the prospect spoke during the walk -> stop it and handle them now.
        if self.presenting:
            self._barge = True
            self._flush_audio()
            for _ in range(20):
                if not self.presenting:
                    break
                await asyncio.sleep(0.1)

        if any(k in low for k in _BUY_SIGNALS):
            print(f"[demo {self.chat_id}] BUY signal -> stripe", flush=True)
            await self.send_payment_link()
            return

        # Stop the auto-walk -> move to questions / closing.
        if self.presenter is not None and any(k in low for k in _STOP_WALK):
            print(f"[demo {self.chat_id}] stop-walk", flush=True)
            await self.speak("Sure. Happy to answer any questions — or just say you're "
                             "ready and I'll send the secure payment link.")
            return

        # Voice slide navigation (only once a live screen-share deck is up).
        if self.presenter is not None and not self.done:
            if any(k in low for k in _NAV_BACK):
                await self.presenter.prev()
                idx = await self.presenter.index()
                print(f"[demo {self.chat_id}] nav back -> slide {idx}", flush=True)
                await self.speak(self._narr_for(idx))
                return
            if any(k in low for k in _NAV_NEXT):
                await self.presenter.next()
                idx = await self.presenter.index()
                print(f"[demo {self.chat_id}] nav next -> slide {idx}", flush=True)
                await self.speak(self._narr_for(idx))
                return

        if any(k in low for k in _PRESENT_SIGNALS) and (os.path.exists(DECK_HTML) or os.path.exists(DECK_PATH)):
            await self.speak("Sure — let me walk you through the deck.")
            await self.present()
            return

        try:
            reply = await asyncio.to_thread(
                self.fast_llm.complete,
                f'Prospect said: "{en}". Answer their actual question directly first; '
                f'no filler, no pivoting to a pitch unless they asked about the product.',
                system=_FAST_SYS, max_tokens=110)
            if reply.strip().upper().startswith("RESEARCH:") and len(norm) > 12:
                q = reply.split(":", 1)[1].strip()
                print(f"[demo {self.chat_id}] exa: {q!r}", flush=True)
                # Filler so there's no dead air while Exa runs (it can be slow).
                await self.speak("Good question — let me check the latest numbers.")
                try:
                    # Hard timeout: Exa has no timeout of its own and was hanging the
                    # whole call (agent went silent). 8s, else answer from what we know.
                    snippets = await asyncio.wait_for(
                        asyncio.to_thread(_exa_search, q), timeout=8.0)
                    reply = await asyncio.to_thread(
                        self.fast_llm.complete,
                        f'Prospect asked: "{en}". Fresh web research:\n{snippets}\n'
                        f'Answer in 2 short spoken sentences using these facts.',
                        system=PRODUCT_CONTEXT, max_tokens=120)
                except Exception as re:
                    print(f"[demo {self.chat_id}] research timeout/err: {re}", flush=True)
                    reply = await asyncio.to_thread(
                        self.fast_llm.complete,
                        f'Prospect asked: "{en}". Give your best 2-sentence spoken answer '
                        f'from what you already know — no filler.',
                        system=PRODUCT_CONTEXT, max_tokens=110)
            asyncio.create_task(asyncio.to_thread(
                self.session.store.append_transcript, self.session.call_id, "prospect", en))
            asyncio.create_task(asyncio.to_thread(
                self.session.store.append_transcript, self.session.call_id, "agent", reply))
        except Exception as e:
            print(f"[demo {self.chat_id}] llm error: {e}", flush=True)
            reply = "Sorry, could you say that again?"
        await self.speak(reply)

    async def _stt_keepalive(self):
        while not self.done:
            await asyncio.sleep(0.5)
            if self.stt is not None and time.time() - self.st["last_fed"] > 2.0:
                for _ in range(50):
                    self.stt.feed(SILENCE16K)
                self.st["last_fed"] = time.time()

    # ---- lifecycle ----
    async def run(self):
        from pytgcalls.types import GroupCallConfig, MediaStream, RecordStream
        from pytgcalls.types.raw import AudioParameters
        await asyncio.to_thread(self.session.store.create_call, self.session.call_id, status="live")
        # Open the call media silently (auto_start) so we don't greet before the
        # prospect is in — the greeting fires on their JOINED event.
        opened = False
        for attempt in range(8):
            try:
                media = MediaStream(SILENCE_MEDIA) if os.path.exists(SILENCE_MEDIA) else MediaStream(DECK_PATH)
                await self.call.play(self.chat_id, media, config=GroupCallConfig(auto_start=True))
                opened = True
                break
            except Exception as e:
                print(f"[demo {self.chat_id}] open attempt {attempt}: {e}", flush=True)
                await asyncio.sleep(1.2)
        if not opened:
            print(f"[demo {self.chat_id}] could not open call", flush=True)
            self.done = True
            return False
        for attempt in range(10):
            try:
                await self.call.record(self.chat_id, RecordStream(
                    audio=True, audio_parameters=AudioParameters(48000, 1)))
                break
            except Exception as e:
                print(f"[demo {self.chat_id}] record retry {attempt}: {e}", flush=True)
                await asyncio.sleep(1.5)
        self.stt = TranscribeStreamer(locale=STT_LOCALE, on_final=self.on_utt)

        async def _stt_runner():
            while not self.done:
                try:
                    await self.stt.run()
                except Exception as e:
                    print(f"[demo {self.chat_id}] stt reconnect: {e}", flush=True)
                await asyncio.sleep(0.3)

        self._tasks = [asyncio.create_task(_stt_runner()),
                       asyncio.create_task(self._stt_keepalive())]
        print(f"[demo {self.chat_id}] LIVE — listening", flush=True)
        return True

    async def teardown(self):
        self.done = True
        for t in self._tasks:
            t.cancel()
        if self._audio_pump_task:
            self._audio_pump_task.cancel()
        if self.presenter:
            try:
                await self.presenter.stop()
            except Exception:
                pass
        try:
            await asyncio.wait_for(self.call.leave_call(self.chat_id), timeout=3.0)
        except Exception:
            pass
        print(f"[demo {self.chat_id}] torn down", flush=True)


class DemoHost:
    def __init__(self, client, call, me):
        self.client = client
        self.call = call
        self.me = me
        self.fast_llm = BedrockLLM(model_id=FAST_MODEL)
        self.closer = Closer()
        self.peer_history: dict[int, list[str]] = {}
        self.active: DemoSession | None = None
        self._lock = asyncio.Lock()
        # Opt-in allowlist: only engage people who registered their Telegram
        # username on the deal-room site (LEADS#index item in DynamoDB). Cached
        # ~15s so new registrations take effect quickly without a read per DM.
        self._allow = {"ts": 0.0, "set": set()}

    def _fetch_leads(self) -> set:
        import boto3
        ddb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        t = ddb.Table(os.environ.get("DDB_TABLE", "dealroom_calls"))
        item = t.get_item(Key={"call_id": "LEADS#index"}).get("Item") or {}
        return {str(u).lstrip("@").lower() for u in (item.get("usernames") or [])}

    async def _allowed(self, username: str | None) -> bool:
        if not username:
            return False
        if time.time() - self._allow["ts"] > 15:
            try:
                self._allow = {"ts": time.time(), "set": await asyncio.to_thread(self._fetch_leads)}
            except Exception as e:
                print(f"[allowlist] fetch err: {e}", flush=True)
        return username.lstrip("@").lower() in self._allow["set"]

    def register(self):
        from pytgcalls import filters as fl
        from pytgcalls.types import StreamFrames, UpdatedGroupCallParticipant

        @self.call.on_update(fl.call_participant())
        async def _part(_, u: UpdatedGroupCallParticipant):
            s = self.active
            if s is None:
                return
            action = getattr(u.action, "name", "")
            uid = u.participant.user_id
            src = getattr(u.participant, "source", None)
            if uid == self.me.id:
                # Capture our own ssrc on ANY self update (the JOINED-only check
                # missed it when we start the call via auto_start) — needed to
                # filter our deck audio so we can listen/barge during the deck.
                if src and s.st.get("self_ssrc") != src:
                    s.on_self_join(src)
            elif action == "JOINED":
                asyncio.create_task(s.on_participant_join(uid))

        @self.call.on_update(fl.stream_frame())
        async def _frames(_, u: StreamFrames):
            if self.active is not None:
                self.active.on_frames(u.frames)

        self.client.add_event_handler(
            self._on_dm, events.NewMessage(incoming=True, func=lambda e: e.is_private))

    async def _on_dm(self, event):
        peer = event.sender_id
        text = (event.raw_text or "").strip()
        if not text:
            return
        # Opt-in only: ignore anyone who didn't register their username on the site.
        sender = await event.get_sender()
        uname = getattr(sender, "username", None)
        if not await self._allowed(uname):
            print(f"[dm] ignored (not registered): @{uname}", flush=True)
            return
        hist = self.peer_history.setdefault(peer, [])
        hist.append(f"Prospect: {text}")
        convo = "\n".join(hist[-8:])
        try:
            reply = await asyncio.to_thread(
                self.fast_llm.complete,
                f"Conversation so far:\n{convo}\n\nWrite your next reply.",
                system=_DM_SYS, max_tokens=160)
        except Exception as e:
            print(f"[dm] llm error: {e}", flush=True)
            reply = "Hi! I'm the DialogBrain agent — want a quick live demo call?"
        start = "DEMO_START" in reply
        reply_clean = reply.replace("DEMO_START", "").strip()
        if reply_clean:
            hist.append(f"Agent: {reply_clean}")
            await event.respond(reply_clean)
        if start:
            await self._start_demo(peer)

    async def _start_demo(self, peer):
        async with self._lock:
            if self.active is not None and not self.active.done:
                await self.client.send_message(
                    peer, "I'm just finishing another live demo — give me a few minutes "
                          "and I'll start yours.")
                return
            try:
                entity = await self.client.get_entity(peer)
                result = await self.client(CreateChatRequest(
                    users=[entity], title="DialogBrain Live Demo"))
                # Telethon 1.37 wraps the result in InvitedUsers(.updates=Updates).
                updates = getattr(result, "updates", result)
                chats = getattr(updates, "chats", None)
                if not chats:
                    raise RuntimeError(f"no chat in CreateChat result: {type(result).__name__}")
                chat = chats[0]
                chat_id = utils.get_peer_id(chat)
            except Exception as e:
                print(f"[demo] create group failed: {e}", flush=True)
                await self.client.send_message(
                    peer, "Couldn't open a demo group just now — mind trying again?")
                return
            session = DemoSession(self, chat_id)
            self.active = session
            ok = await session.run()
            if ok:
                # Call is live now — point the prospect straight at it.
                await self.client.send_message(
                    chat_id, "📞 I've started a voice call in this group — tap **Join** at "
                             "the top to hop in. I'll walk you through a quick demo, then "
                             "answer anything. 🎤")
            else:
                await self.client.send_message(
                    chat_id, "I couldn't start the call just now — give me a moment and I'll "
                             "try again.")
                self.active = None


async def main():
    client = TelegramClient(StringSession(os.environ["TG_SESSION_STRING"]),
                            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    from pytgcalls import PyTgCalls
    await client.start()
    me = await client.get_me()
    print(f"[host] logged in @{me.username} id={me.id}", flush=True)
    await client.get_dialogs()

    call = PyTgCalls(client)
    await call.start()
    try:
        from ntgcalls import set_log_level
        set_log_level(4)
    except Exception:
        pass

    host = DemoHost(client, call, me)
    host.register()
    print("DEMO HOST up — DM @{} to start a live demo".format(me.username), flush=True)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
