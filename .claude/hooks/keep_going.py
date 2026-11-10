"""Stop hook: keep the autonomous Tempo build running until PROGRESS.md line 1 says DONE or BLOCKED.

Caps at 60 forced continuations so it can never loop forever. Delete this file to disable.
"""
import json, pathlib, sys

progress = pathlib.Path("PROGRESS.md")
first = progress.read_text().splitlines()[0] if progress.exists() and progress.read_text().strip() else ""
counter = pathlib.Path(".claude/hooks/.keep_going_count")
n = int(counter.read_text()) if counter.exists() else 0
if "BUILD STATUS: DONE" in first or "BUILD STATUS: BLOCKED" in first or n >= 60:
    sys.exit(0)
counter.write_text(str(n + 1))
print(json.dumps({
    "decision": "block",
    "reason": "Not done. Re-read PROGRESS.md and docs/BUILD_DIRECTIVE.md and continue with the next unfinished step. "
              "Do not wait for humans. Set PROGRESS.md line 1 to 'BUILD STATUS: DONE' only when section 14 is complete, "
              "or 'BUILD STATUS: BLOCKED ON HUMAN: <reason>' if you truly need a human.",
}))
