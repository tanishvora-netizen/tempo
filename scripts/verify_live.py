"""Check a deployed Tempo instance: `make verify-live URL=https://...`.

Reads only public endpoints of the given URL (the humans' own deployment). Waits up to ~2 minutes for a
sleeping free-tier instance to wake.
"""

import json
import sys
import time
import urllib.request

WAKE_TIMEOUT_S = 150
CHECKS = ("/health", "/api/state", "/api/bills", "/api/forecast", "/api/evaluate", "/api/whatif/presets")


def get(url: str, timeout: float = 60.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "tempo-verify-live"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def wait_awake(base: str) -> None:
    deadline = time.monotonic() + WAKE_TIMEOUT_S
    while True:
        try:
            if get(base + "/health", 30)[0] == 200:
                return
        except OSError:
            pass
        if time.monotonic() > deadline:
            sys.exit(f"{base} did not answer /health within {WAKE_TIMEOUT_S}s")
        time.sleep(5)


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        sys.exit("usage: verify_live.py https://<your-render-url>")
    base = sys.argv[1].rstrip("/")
    wait_awake(base)
    failures = 0
    for path in CHECKS:
        started = time.perf_counter()
        status, body = get(base + path)
        ok = status == 200
        failures += not ok
        print(
            f"{'ok ' if ok else 'BAD'} {path:28s} {status} {len(body):>8,} bytes {time.perf_counter() - started:.2f}s"
        )
    state = json.loads(get(base + "/api/state")[1])["data"]
    print("provenance:", state["provenance"])
    print("provider:", state["provider"]["label"])
    if not state["provenance"]["hash_ok"]:
        print("note: served results are from build", state["provenance"]["input_hash"])
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
