"""Research-to-deck generator: Exa → Claude (Bedrock) → a presentable HTML deck.

The presenter agent opens a URL and screen-shares it into the call, so we render
a self-contained reveal.js deck (keyboard/auto-walkable) the agent can present.

  build_deck(topic) -> writes deck.html
    1. Exa: gather fresh, cited web context on the topic / prospect.
    2. Claude (Bedrock Sonnet/Opus): turn research into 5-7 punchy slides (JSON).
    3. Render a dark, branded reveal.js deck.

Run: uv run --with boto3 --with exa-py python deck_gen.py "DialogBrain for fintech sales"
Model: BEDROCK_MODEL_ID (default sonnet); pass --opus for Opus.
"""
from __future__ import annotations

import json
import os
import sys

from exa_py import Exa

from bedrock_client import BedrockLLM

_exa = Exa(os.environ["EXA_API_KEY"])

_SYS = (
    "You are a top-tier startup pitch designer. From the research, produce a punchy, "
    "investor/sales-grade slide deck. Return ONLY JSON: "
    '{"title": str, "subtitle": str, "slides": [{"heading": str, "bullets": [str, str, str], '
    '"narration": str}]}. '
    "5-7 slides. Bullets <= 9 words, concrete, no fluff. "
    "narration = what the presenter SAYS for that slide, 1-2 spoken sentences (<= 35 words), "
    "natural and persuasive, expands on the bullets. Ground claims in the research."
)


def research(topic: str, n: int = 6) -> tuple[str, list[dict]]:
    res = _exa.search_and_contents(topic, num_results=n, text={"max_characters": 1200}, type="auto")
    results = getattr(res, "results", []) or []
    ctx = "\n\n".join(f"[{i+1}] {r.title}\n{(r.text or '')[:1000]}" for i, r in enumerate(results))
    sources = [{"title": r.title, "url": r.url} for r in results]
    return ctx, sources


def author(topic: str, ctx: str, llm: BedrockLLM) -> dict:
    prompt = f"Topic: {topic}\n\nResearch:\n{ctx}\n\nReturn the deck JSON now."
    raw = llm.complete(prompt, system=_SYS, max_tokens=1400)
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    return json.loads(raw)


def render_html(deck: dict) -> str:
    slides = [f'<section><h1 class="title">{deck["title"]}</h1><p class="sub">{deck.get("subtitle","")}</p></section>']
    for s in deck["slides"]:
        items = "".join(f"<li>{b}</li>" for b in s.get("bullets", []))
        slides.append(f'<section><h2>{s["heading"]}</h2><ul>{items}</ul></section>')
    body = "\n".join(slides)
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>{deck['title']}</title>
<link rel=stylesheet href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Familjen+Grotesk:wght@400;500&display=swap" rel=stylesheet>
<style>
 :root{{--bg:#0a0b0e;--fg:#e7e9ee;--cy:#4cc2ff;--am:#f5b62c;}}
 .reveal{{font-family:'Familjen Grotesk',sans-serif;color:var(--fg);}}
 .reveal .slides{{text-align:left;}}
 body,.reveal-viewport{{background:
   radial-gradient(800px 500px at 80% -10%,rgba(76,194,255,.14),transparent 60%),
   radial-gradient(700px 500px at -10% 110%,rgba(245,182,44,.10),transparent 55%),#0a0b0e;}}
 .reveal h1,.reveal h2{{font-family:'Syne',sans-serif;font-weight:800;letter-spacing:-.02em;}}
 .reveal h1.title{{font-size:2.6em;line-height:1.05;}}
 .reveal h2{{font-size:1.9em;color:#fff;border-left:4px solid var(--cy);padding-left:.4em;}}
 .reveal .sub{{color:#8b94a7;font-size:1.1em;margin-top:.4em;}}
 .reveal ul{{margin-top:.7em;}}
 .reveal li{{margin:.45em 0;font-size:1.15em;}}
 .reveal li::marker{{color:var(--am);}}
</style></head><body>
<div class=reveal><div class=slides>
{body}
</div></div>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
<script>Reveal.initialize({{hash:true, transition:'slide'}});</script>
</body></html>"""


def build_deck(topic: str, *, model: str | None = None, out: str = "deck.html") -> dict:
    llm = BedrockLLM(model_id=model) if model else BedrockLLM()
    ctx, sources = research(topic)
    deck = author(topic, ctx, llm)
    with open(out, "w") as f:
        f.write(render_html(deck))
    # Emit the structured deck alongside the HTML so the video renderer can
    # narrate each slide (Polly) without re-calling the LLM.
    deck_json = {**deck, "sources": sources}
    with open(os.path.splitext(out)[0] + ".json", "w") as f:
        json.dump(deck_json, f, indent=2)
    return {"title": deck["title"], "slides": len(deck["slides"]), "sources": sources, "out": out}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--opus"]
    topic = args[0] if args else "DialogBrain — autonomous AI agents that run live sales calls"
    model = "global.anthropic.claude-opus-4-6" if "--opus" in sys.argv else None
    info = build_deck(topic, model=model)
    print(json.dumps(info, indent=2)[:600])
