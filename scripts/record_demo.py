"""Record the backup demo video (1440x900) with Playwright: `make demo-video`.

Starts the app in host mode on a free port, walks the demo path with pauses for voiceover, and saves the video
to docs/demo/tempo-demo.webm. The humans add the voiceover; nothing here calls an external service.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "demo"
SIZE = {"width": 1440, "height": 900}
BEAT_MS = 2_000


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int, audit_path: Path) -> subprocess.Popen:
    env = {**os.environ, "TEMPO_PROVIDER": "cached", "TEMPO_AUDIT_PATH": str(audit_path)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(150):
        try:
            if urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).status == 200:
                return proc
        except OSError:
            time.sleep(0.2)
    proc.terminate()
    sys.exit("server did not start")


def injection_vendor() -> str:
    """The vendor whose invoice carries the prompt-injection text (from the committed dataset)."""
    sys.path.insert(0, str(REPO))
    from tempo.data.store import load_dataset

    ds = load_dataset("demo")
    inv = next(i for i in ds.invoices if i.tag == "injection")
    return next(v.name for v in ds.vendors if v.id == inv.vendor_id)


def click_first(page: Page, selector: str, wait_ms: int = BEAT_MS) -> bool:
    """Click the first match if it exists, then pause for the voiceover."""
    loc = page.locator(selector).first
    if not loc.count():
        return False
    loc.click()
    page.wait_for_timeout(wait_ms)
    return True


def pause(page: Page, beats: float = 1.0, scroll: int = 0) -> None:
    if scroll:
        page.mouse.wheel(0, scroll)
    page.wait_for_timeout(int(BEAT_MS * beats))


def walk(page: Page, base: str) -> None:
    """The DEMO_SCRIPT path, about three minutes, with pauses sized for the three speakers' lines."""
    page.goto(f"{base}/#/overview")
    pause(page, 6)  # Anthony: problem, the 37% hook, why Ramp
    click_first(page, '[data-view="both"]', BEAT_MS * 3)  # Tanish: the fan, before vs after
    page.goto(f"{base}/#/run")
    pause(page, 1.5)
    click_first(page, "tr[data-bill]", BEAT_MS * 4)  # read a reason sentence
    page.keyboard.press("Escape")
    page.goto(f"{base}/#/whatif")
    pause(page, 1.5)
    page.locator("[data-preset]").nth(1).click()  # biggest customer pays 14 days late
    pause(page, 4)
    pause(page, 3, scroll=700)  # decisions that flipped, with reasons
    page.goto(f"{base}/#/proof")
    pause(page, 3)
    pause(page, 3, scroll=800)
    click_first(page, '[data-model="true"]', BEAT_MS * 3)  # the true-model check
    pause(page, 3, scroll=1200)  # ablations and extraction accuracy
    page.goto(f"{base}/#/review")  # Namith: the AI layer
    pause(page, 1.5)
    page.get_by_text(injection_vendor()).first.click()  # the prompt-injection invoice
    pause(page, 5)
    click_first(page, "[data-accept]", BEAT_MS * 3)
    page.goto(f"{base}/#/overview")
    pause(page, 1)
    click_first(page, '[data-open="negotiate"]', BEAT_MS * 2)
    click_first(page, "[data-vendor]", BEAT_MS * 3)
    click_first(page, "button:has-text('Draft offer')", BEAT_MS * 4)
    click_first(page, "[data-reply]", BEAT_MS * 3)
    click_first(page, "[data-accept-terms]", BEAT_MS * 2)
    page.keyboard.press("Escape")
    pause(page, 1)
    if click_first(page, "[data-approve]", BEAT_MS * 2):
        name = page.locator("[data-name]").first
        if name.count():
            name.fill("Dana Ortiz, CFO")
        click_first(page, "[data-confirm]", BEAT_MS * 5)  # audit entry and Ramp payload preview
        pause(page, 3, scroll=900)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    port = free_port()
    tmp = OUT / ".recording"
    shutil.rmtree(tmp, ignore_errors=True)
    server = start_server(port, tmp / "audit.jsonl")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport=SIZE, record_video_dir=str(tmp), record_video_size=SIZE)
            page = context.new_page()
            walk(page, f"http://127.0.0.1:{port}")
            video = page.video
            context.close()
            browser.close()
            target = OUT / "tempo-demo.webm"
            Path(video.path()).replace(target)
            print(f"saved {target}")
    finally:
        server.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
