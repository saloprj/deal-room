"""Live browser screen-share presenter — shares a reveal.js deck into a TG call.

Standalone (no DialogBrain deps). Launches headless Chromium (chrome-headless-shell
via Playwright), loads the reveal.js deck.html, and pumps the tab into the Telegram
group call as a SCREEN presentation:

  CDP Page.captureScreenshot(jpeg) -> JPEG->I420 -> call.send_frame(Device.SCREEN)

Slide nav is driven over CDP (Reveal.slide / next / prev). The ntgcalls fork carries
the outgoing screen-share patches (build 2.1.0+canary.01cc63f6).

The call must already be registered with a Stream(... screen=VideoStream(EXTERNAL) ...)
by the DemoSession (together with the external-audio microphone) — this class owns the
browser, the slide navigation, and the video send pump only.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os

import numpy as np
from PIL import Image

DECK_HTML = os.environ.get("DECK_HTML", "/media/deck.html")


def _rgb_to_i420(rgb: np.ndarray, w: int, h: int) -> bytes:
    """BT.601 limited-range RGB->YUV 4:2:0 planar (mirror of the receive-side decode)."""
    r = rgb[:, :, 0].astype(np.float32)
    g = rgb[:, :, 1].astype(np.float32)
    b = rgb[:, :, 2].astype(np.float32)
    y = np.clip(0.257 * r + 0.504 * g + 0.098 * b + 16, 0, 255).astype(np.uint8)
    u = np.clip(-0.148 * r - 0.291 * g + 0.439 * b + 128, 0, 255).astype(np.uint8)
    v = np.clip(0.439 * r - 0.368 * g - 0.071 * b + 128, 0, 255).astype(np.uint8)
    return y.tobytes() + u[0::2, 0::2].tobytes() + v[0::2, 0::2].tobytes()


def _jpeg_to_i420(jpeg: bytes, w: int, h: int) -> bytes:
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    if img.width != w or img.height != h:
        img = img.resize((w, h))
    return _rgb_to_i420(np.asarray(img, dtype=np.uint8), w, h)


class LivePresenter:
    def __init__(self, width: int = 1280, height: int = 720, fps: int = 3):
        self.w, self.h, self.fps = width, height, fps
        self._pw = None
        self.browser = None
        self.page = None
        self.cdp = None
        self.call = None
        self.chat_id = None
        self._pump_task: asyncio.Task | None = None
        self.stopped = False

    async def launch(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        # headless=True -> chrome-headless-shell -> viewport == capture surface
        self.browser = await self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--hide-scrollbars", "--disable-dev-shm-usage",
                  "--disable-gpu", "--disable-smooth-scrolling"])
        self.page = await self.browser.new_page(viewport={"width": self.w, "height": self.h})
        await self.page.goto(f"file://{DECK_HTML}")
        await self.page.wait_for_timeout(1000)  # reveal.js init
        self.cdp = await self.page.context.new_cdp_session(self.page)
        print(f"[presenter] browser up, deck loaded ({DECK_HTML})", flush=True)

    async def _eval(self, js: str):
        try:
            r = await self.cdp.send("Runtime.evaluate",
                                    {"expression": js, "returnByValue": True})
            return r.get("result", {}).get("value")
        except Exception as e:
            print(f"[presenter] eval err: {e}", flush=True)
            return None

    async def total(self) -> int:
        v = await self._eval("Reveal.getTotalSlides()")
        try:
            return int(v)
        except Exception:
            return 0

    async def index(self) -> int:
        v = await self._eval("Reveal.getIndices().h")
        try:
            return int(v)
        except Exception:
            return 0

    async def goto(self, i: int):
        await self._eval(f"Reveal.slide({i})")

    async def next(self):
        await self._eval("Reveal.next()")

    async def prev(self):
        await self._eval("Reveal.prev()")

    def start_video_pump(self, call, chat_id):
        self.call, self.chat_id = call, chat_id
        self.stopped = False
        self._pump_task = asyncio.create_task(self._video_pump())

    async def _video_pump(self):
        from pytgcalls.types import Device, Frame
        info = Frame.Info(width=self.w, height=self.h)
        interval = 1.0 / float(self.fps)
        loop = asyncio.get_running_loop()
        nt = loop.time()
        fails = 0
        n = 0
        while not self.stopped:
            try:
                resp = await self.cdp.send(
                    "Page.captureScreenshot",
                    {"format": "jpeg", "quality": 70, "captureBeyondViewport": False})
                data = resp.get("data") if isinstance(resp, dict) else None
                if data:
                    i420 = await asyncio.to_thread(
                        _jpeg_to_i420, base64.b64decode(data), self.w, self.h)
                    await self.call.send_frame(self.chat_id, Device.SCREEN, i420, info)
                    n += 1
                    if n % 30 == 0:
                        print(f"[presenter] video frames={n}", flush=True)
                    fails = 0
            except Exception as e:
                fails += 1
                if fails == 1 or fails % 30 == 0:
                    print(f"[presenter] pump err ({fails}): {e}", flush=True)
                if fails > 90:
                    print("[presenter] pump giving up", flush=True)
                    break
            nt += interval
            d = nt - loop.time()
            await asyncio.sleep(d if d > 0 else 0)

    async def stop(self):
        self.stopped = True
        if self._pump_task:
            self._pump_task.cancel()
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        print("[presenter] stopped", flush=True)
