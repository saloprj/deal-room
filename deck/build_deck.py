"""Generate the Deal-Room pitch deck (.pptx) for the SuperAI NEXT submission.

Punchy, visual, dark theme. Run: uv run --with python-pptx python build_deck.py
Output: deal-room.pptx  (upload to Google Drive for the BUIDL submission).
The Top-5 stage version embeds the demo screen-recording on the DEMO slide.
"""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

BG = RGBColor(0x0B, 0x0E, 0x14)
FG = RGBColor(0xE6, 0xE9, 0xEF)
MUTE = RGBColor(0x8B, 0x94, 0xA7)
ACCENT = RGBColor(0x38, 0xBD, 0xF8)
GREEN = RGBColor(0x34, 0xD3, 0x99)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]


def slide():
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = BG
    return s


def tb(s, x, y, w, h):
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.text_frame.word_wrap = True
    return box.text_frame


def line(tf, text, size, color=FG, bold=False, align=PP_ALIGN.LEFT, space=6, first=False):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_after = Pt(space)
    r = p.add_run(); r.text = text
    r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color
    r.font.name = "Segoe UI"
    return p


def title_slide(kicker, title, sub):
    s = slide()
    tf = tb(s, 0.9, 2.2, 11.5, 3)
    line(tf, kicker, 16, ACCENT, bold=True, first=True)
    line(tf, title, 44, FG, bold=True, space=10)
    line(tf, sub, 20, MUTE)
    return s


def content_slide(title, bullets):
    s = slide()
    tf = tb(s, 0.9, 0.7, 11.5, 1)
    line(tf, title, 30, ACCENT, bold=True, first=True)
    bf = tb(s, 0.9, 1.9, 11.5, 5.2)
    for i, (txt, *opt) in enumerate(bullets):
        col = opt[0] if opt else FG
        sz = opt[1] if len(opt) > 1 else 20
        line(bf, txt, sz, col, first=(i == 0), space=12)
    return s


# 1 — Title
title_slide("SuperAI NEXT Hackathon 2026 · Team dialogbrain",
            "Deal-Room",
            "An autonomous AI agent that runs a live multilingual sales call — "
            "presents, translates, researches, and closes the deal.")

# 2 — The theme / problem
content_slide("The brief: build anything, but make it agentic", [
    ("Sales calls are the highest-value, least-automated conversation a business has.", FG, 22),
    ("Deal-Room puts an autonomous agent on a live Telegram group call that does the whole thing:", MUTE, 18),
    ("•  Presents the deck (screen-share)", FG),
    ("•  Translates the conversation in real time", FG),
    ("•  Answers hard questions with live web research", FG),
    ("•  Closes the deal by taking payment — with a human approving the close", FG),
])

# 3 — The money shot
content_slide("What the judges see", [
    ("Agent joins the call → presents → prospect speaks another language → live translation", FG, 20),
    ("→ tough question → live Exa web lookup → spoken answer + slide update", FG, 20),
    ("→ buying signal → operator taps Approve → Stripe link in chat → payment confirmed.", FG, 20),
    ("One self-running agent. Real money moved. All on stage.", ACCENT, 22),
])

# 4 — Architecture
content_slide("Architecture — the agent crew", [
    ("Orchestrator   decides present / answer / research / close   (Bedrock)", FG, 19),
    ("Presenter      screen-shares + narrates the deck", FG, 19),
    ("Translator     real-time 2-way speech (AWS Translate + Polly)", FG, 19),
    ("Researcher     live web grounding   (Exa)", FG, 19),
    ("Closer         hosted checkout + payment   (Stripe)", FG, 19),
    ("Runtime: Python call worker on AWS (ECS/EC2) · Bedrock reasoning · DynamoDB control bus · "
     "Vercel dashboard (AI Gateway + approve gate).", MUTE, 16),
])

# 5 — Integrations
content_slide("Four sponsors, each load-bearing", [
    ("AWS      Bedrock (Claude) reasoning · DynamoDB state · Polly/Transcribe/Translate voice · ECS/EC2 runtime", FG, 18),
    ("Vercel   AI Gateway + AI SDK dashboard = the operator console & human-approval gate (live URL)", FG, 18),
    ("Exa      the agent's live senses — real-time web answers mid-call", FG, 18),
    ("Stripe   the close — a real hosted checkout the agent triggers on approval", FG, 18),
])

# 6 — Judging criteria
content_slide("Maps to all 7 judging criteria", [
    ("Agent Overview · Autonomy & Decision-Making · Actions & Tool Use", FG, 19),
    ("Orchestration (multi-agent) · Human-in-the-Loop (approve-to-close)", FG, 19),
    ("Failure Handling (Exa-empty fallback, translation retry) · Demo & Presentation", FG, 19),
    ("Every criterion is exercised in a single end-to-end call.", ACCENT, 20),
])

# 7 — Live & verified
content_slide("Built & verified live (not slideware)", [
    ("✓  Bedrock reasoning — global.anthropic.claude-sonnet-4-6", GREEN, 18),
    ("✓  Exa Researcher — returns cited, current answers", GREEN, 18),
    ("✓  Stripe Closer — real hosted test checkout", GREEN, 18),
    ("✓  DynamoDB control bus — worker ↔ dashboard", GREEN, 18),
    ("✓  Telegram call — agent joins & transmits audio", GREEN, 18),
    ("✓  Vercel dashboard — LIVE, shows a real call end-to-end", GREEN, 18),
    ("github.com/saloprj/deal-room", ACCENT, 16),
])

# 8 — Demo / close
s = title_slide("Demo", "Watch the agent close a deal — live, in two languages.",
                "Team dialogbrain · github.com/saloprj/deal-room")

prs.save("deal-room.pptx")
print("wrote deal-room.pptx with", len(prs.slides._sldIdLst), "slides")
