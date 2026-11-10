"""Start the app in host mode (TEMPO_PROVIDER=cached) on a free local port for Playwright tests."""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_S = 30


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    port = _free_port()
    env = {
        **os.environ,
        "TEMPO_PROVIDER": "cached",
        "TEMPO_AUDIT_PATH": str(tmp_path_factory.mktemp("audit") / "audit.jsonl"),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            if urllib.request.urlopen(base + "/health", timeout=1).status == 200:
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("server did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)
