"""Record the backup demo video (1440x900) with Playwright: `make demo-video`.

Starts the app in host mode on a free port, walks the demo path with pauses for voiceover, and saves the video
to docs/demo/tempo-demo.webm. The humans add the voiceover; nothing here calls an external service.
"""

import os
import re
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
BEAT_MS = 2_500


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


def click_if(page: Page, role: str, name: str) -> None:
    loc = page.get_by_role(role, name=name).first  # type: ignore[arg-type]
    if loc.count():
        loc.click()
        page.wait_for_timeout(BEAT_MS)


def walk(page: Page, base: str) -> None:
    """Overview -> Payment run detail -> What-if preset -> Proof -> Needs review -> Negotiate -> Approve."""
    page.goto(f"{base}/#/overview")
    page.wait_for_timeout(BEAT_MS * 2)
    page.goto(f"{base}/#/run")
    page.wait_for_timeout(BEAT_MS)
    page.get_by_role("button", name=re.compile("open details")).first.click()
    page.wait_for_timeout(BEAT_MS * 2)
    page.keyboard.press("Escape")
    page.goto(f"{base}/#/whatif")
    page.wait_for_timeout(BEAT_MS)
    page.get_by_role("button", name=re.compile("14 days late")).first.click()
    page.wait_for_timeout(BEAT_MS * 3)
    page.goto(f"{base}/#/proof")
    page.wait_for_timeout(BEAT_MS * 2)
    page.mouse.wheel(0, 900)
    page.wait_for_timeout(BEAT_MS * 2)
    page.goto(f"{base}/#/review")
    page.wait_for_timeout(BEAT_MS * 2)
    page.goto(f"{base}/#/overview")
    click_if(page, "button", "Negotiate terms")
    page.keyboard.press("Escape")
    click_if(page, "button", "Approve")
    page.wait_for_timeout(BEAT_MS)


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
