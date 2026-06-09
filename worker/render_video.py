"""Render a Deal-Room deck into a narrated MP4 — entirely on AWS.

Pipeline (all AWS-native, no external presentation infra):
  deck.json (Exa->Bedrock, from deck_gen)  +  deck.html (reveal.js)
    1. Playwright/Chromium screenshots each slide at 1280x720.
    2. Amazon Polly narrates each slide's `narration` (translated if needed).
    3. ffmpeg turns each (slide image + narration mp3) into a segment,
       then concatenates into deck.mp4.

The MP4 is the "presentation": it is streamed into the Telegram call by
call_worker (pytgcalls MediaStream) as the agent's screen-share, and it is also
a standalone, recordable demo artifact.

Run (inside the worker image, which has chromium + ffmpeg):
  python render_video.py --deck deck.json --html deck.html --out deck.mp4 [--lang ru]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import tempfile

import voice

W, H = 1280, 720


async def _shoot_slides(html_path: str, n: int, outdir: str) -> list[str]:
    """Screenshot slides 0..n-1 of the reveal.js deck; return PNG paths."""
    from playwright.async_api import async_playwright

    url = "file://" + os.path.abspath(html_path)
    shots: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--hide-scrollbars"])
        page = await browser.new_page(viewport={"width": W, "height": H})
        await page.goto(url)
        await page.wait_for_timeout(800)  # reveal.js init
        for i in range(n):
            await page.evaluate(f"Reveal.slide({i})")
            await page.wait_for_timeout(500)  # transition settle
            shot = os.path.join(outdir, f"slide_{i:02d}.png")
            await page.screenshot(path=shot)
            shots.append(shot)
        await browser.close()
    return shots


def _narration_segment(img: str, text: str, lang: str, outdir: str, idx: int) -> str:
    """One slide -> one mp4 segment (image shown for the length of its narration)."""
    say = voice.translate(text, source="en", target=lang) if lang != "en" else text
    mp3 = os.path.join(outdir, f"narr_{idx:02d}.mp3")
    with open(mp3, "wb") as f:
        f.write(voice.synthesize_mp3(say or " ", lang))
    seg = os.path.join(outdir, f"seg_{idx:02d}.mp4")
    # loop the still image for the duration of the audio (-shortest), pad audio tail.
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", img, "-i", mp3,
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-af", "apad=pad_dur=0.6",
        "-shortest", "-r", "25", "-vf", f"scale={W}:{H}", seg,
    ], check=True, capture_output=True)
    return seg


def build_video(deck_json: str, html: str, out: str = "deck.mp4", lang: str = "en") -> dict:
    deck = json.load(open(deck_json))
    slides = deck["slides"]
    # slide 0 of the HTML is the title; narrate it with title+subtitle.
    narrations = [f'{deck.get("title","")}. {deck.get("subtitle","")}'.strip()]
    narrations += [s.get("narration") or " ".join(s.get("bullets", [])) for s in slides]
    n = len(narrations)

    with tempfile.TemporaryDirectory() as tmp:
        shots = asyncio.run(_shoot_slides(html, n, tmp))
        segs = [_narration_segment(shots[i], narrations[i], lang, tmp, i) for i in range(n)]
        listf = os.path.join(tmp, "list.txt")
        with open(listf, "w") as f:
            for s in segs:
                f.write(f"file '{s}'\n")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf,
                        "-c", "copy", out], check=True, capture_output=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", out], capture_output=True, text=True).stdout.strip()
    return {"out": out, "slides": n, "seconds": dur, "lang": lang}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="deck.json")
    ap.add_argument("--html", default="deck.html")
    ap.add_argument("--out", default="deck.mp4")
    ap.add_argument("--lang", default="en")
    a = ap.parse_args()
    print(json.dumps(build_video(a.deck, a.html, a.out, a.lang), indent=2))
