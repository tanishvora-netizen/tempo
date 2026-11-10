#!/usr/bin/env bash
# Tempo harness setup. Run ONCE from the root of the team repo, BEFORE launching Claude Code:
#   bash tempo_setup.sh
# Put TEMPO_BUILD_PROMPT.md in the repo root (or next to this script) first.
# Installs, project scope only: ECC plugin + lean rules, Superpowers, frontend-design, ui-ux-pro-max (CLI form),
# find-skills (discovery results saved for Claude), Ollama + a local model, a Python 3.12 venv with the stack
# and Playwright, Tailwind CLI; writes the 5-member review council, a keep-going Stop hook, and a CLAUDE.md pointer.
# Everything that downloads code happens here, so Claude Code's auto mode never has to ask during the night.
# Safe to re-run.
set -uo pipefail

ok()   { printf "  [ok]   %s\n" "$1"; }
warn() { printf "  [warn] %s\n" "$1"; }
die()  { printf "  [fail] %s\n" "$1"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== 0. Prerequisites"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Run this from inside the team's git repo."
for c in git node npm npx claude curl; do command -v "$c" >/dev/null || die "Missing: $c"; done
if ! command -v python3.12 >/dev/null; then
  command -v brew >/dev/null && brew install python@3.12 </dev/null || die "Python 3.12 required: brew install python@3.12"
fi
ok "python3.12 $(python3.12 -c 'import sys;print(sys.version.split()[0])'), node $(node -v), $(claude --version 2>/dev/null | head -1)"
DIRECTIVE=""
for p in "TEMPO_BUILD_PROMPT.md" "$HERE/TEMPO_BUILD_PROMPT.md"; do [ -f "$p" ] && DIRECTIVE="$p" && break; done
[ -n "$DIRECTIVE" ] || die "TEMPO_BUILD_PROMPT.md not found in the repo root or next to this script."

echo "== 1. Plugins (project scope)"
claude plugin marketplace add anthropics/claude-plugins-official </dev/null || true
claude plugin marketplace add affaan-m/ECC </dev/null || true
claude plugin install ecc@ecc --scope project </dev/null && ok "ecc@ecc" || warn "ECC install failed. Inside Claude: /plugin marketplace add https://github.com/affaan-m/ECC, then /plugin install ecc@ecc (project scope)"
claude plugin install superpowers@claude-plugins-official --scope project </dev/null && ok "superpowers" || warn "superpowers failed. Inside Claude: /plugin install superpowers@claude-plugins-official"
claude plugin install frontend-design@claude-plugins-official --scope project </dev/null && ok "frontend-design" || warn "frontend-design failed (optional)"

echo "== 2. ECC rules (lean subset; plugins cannot ship rules)"
rm -rf /tmp/ecc-src && git clone --depth 1 -q https://github.com/affaan-m/ECC.git /tmp/ecc-src || die "Could not clone ECC"
mkdir -p .claude/rules/ecc
cp -R /tmp/ecc-src/rules/python .claude/rules/ecc/
for f in coding-style testing security code-review; do
  [ -f "/tmp/ecc-src/rules/common/$f.md" ] && cp "/tmp/ecc-src/rules/common/$f.md" .claude/rules/ecc/
done
ok "rules: common/{coding-style,testing,security,code-review} + python"

echo "== 3. ui-ux-pro-max (CLI form: one skill, stable script path)"
npx -y ui-ux-pro-max-cli init --ai claude </dev/null
[ -f .claude/skills/ui-ux-pro-max/scripts/search.py ] && ok "ui-ux-pro-max at .claude/skills/ui-ux-pro-max/" || warn "ui-ux-pro-max missing; retry: npx ui-ux-pro-max-cli init --ai claude"

echo "== 4. find-skills: install, then run discovery here so Claude never has to execute npx at night"
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]'); NODE_MINOR=$(node -p 'process.versions.node.split(".")[1]')
mkdir -p tooling
if [ "$NODE_MAJOR" -gt 22 ] || { [ "$NODE_MAJOR" -eq 22 ] && [ "$NODE_MINOR" -ge 20 ]; }; then
  DISABLE_TELEMETRY=1 npx -y skills add vercel-labs/skills --skill find-skills -a claude-code -y </dev/null && ok "find-skills" || warn "find-skills install failed (optional)"
  : > tooling/find-skills.txt
  for q in "fastapi" "pytest" "playwright" "data visualization" "chart.js" "operations research optimization" "financial dashboard"; do
    echo "### npx skills find \"$q\"" >> tooling/find-skills.txt
    DISABLE_TELEMETRY=1 npx -y skills find "$q" </dev/null >> tooling/find-skills.txt 2>&1 || echo "(search failed)" >> tooling/find-skills.txt
  done
  ok "discovery results in tooling/find-skills.txt"
else
  warn "Node $(node -v) < 22.20: skipping find-skills (optional)"
fi

echo "== 5. Python 3.12 venv with the stack and Playwright, plus Tailwind CLI"
[ -d .venv ] || python3.12 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q fastapi "uvicorn[standard]" numpy scipy pandas pydantic httpx pytest hypothesis ruff \
  ollama pypdf python-multipart playwright pytest-playwright && ok "venv packages" || warn "pip install had errors"
.venv/bin/playwright install chromium >/dev/null 2>&1 && ok "Playwright chromium" || warn "playwright install chromium failed"
[ -f package.json ] || npm init -y >/dev/null 2>&1
npm i -D @tailwindcss/cli tailwindcss chart.js @fontsource/inter @fontsource/ibm-plex-sans lucide-static >/dev/null 2>&1 \
  && ok "Tailwind CLI, Chart.js, fonts, Lucide icons (devDependencies, vendored later)" || warn "npm devDependencies install failed"

echo "== 6. Local AI runtime (no external APIs): Ollama + an open-weights model sized to this Mac's RAM"
if ! command -v ollama >/dev/null; then
  if command -v brew >/dev/null; then brew install ollama </dev/null && ok "installed ollama" || warn "brew install ollama failed: get it at https://ollama.com/download"
  else warn "No Ollama and no Homebrew: install from https://ollama.com/download, then re-run"; fi
fi
if command -v ollama >/dev/null; then
  if ! curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    brew services start ollama >/dev/null 2>&1 || (nohup ollama serve >/tmp/ollama_serve.log 2>&1 &)
    for i in $(seq 30); do curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break; sleep 1; done
  fi
  MEM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 8589934592) / 1073741824 ))
  if [ "$MEM_GB" -ge 16 ]; then MODEL="qwen3:8b"; else MODEL="gemma3:4b"; fi
  echo "TEMPO_LOCAL_MODEL=$MODEL" > .tempo_local_model
  nohup ollama pull "$MODEL" >/tmp/ollama_pull.log 2>&1 &
  ok "pulling $MODEL in the background (${MEM_GB} GB RAM); log: /tmp/ollama_pull.log"
fi

echo "== 7. Review council (.claude/agents must exist before Claude starts)"
mkdir -p .claude/agents
write_agent() { # name, tools, description, persona
cat > ".claude/agents/$1.md" <<EOF
---
name: $1
description: "$3"
tools: $2
model: opus
effort: high
maxTurns: 12
---
$4

You are one of five independent reviewers on Tempo's council. The chair (the main session) gives you ONE decision or artifact plus file paths. You have not seen the conversation; read the files you need. You have no web access; review local files, localhost, and screenshots only.
Return at most 300 words, in this shape:
1. Verdict: SHIP, FIX, or BLOCK.
2. Top 3 issues, each with file:line (or screenshot name), why it matters, and one concrete fix.
3. The one thing the other reviewers will probably miss.
Do not edit files. Do not spawn agents. Be specific and skeptical; praise is not useful.
EOF
}
write_agent council-quant "Read, Grep, Glob, Bash" \
  "Council reviewer for operations research and statistics. Use when the chair convenes the council on the optimizer, chance constraint, forecast, evaluation, or any formula." \
  "You are a senior operations-research scientist and statistician. Check the MILP formulation, the sample-average chance constraint, big-M validity and tightness, the quantile-cut row reduction, scenario counts, seeds and certification, one-sided Wilson bounds, forecast fitting (pooled lognormal, truncation, the common factor), and every formula against its docstring. You may run pytest or small Python checks with .venv/bin/python; never modify files."
write_agent council-controller "Read, Grep, Glob" \
  "Council reviewer acting as a senior AP and treasury controller. Use when the chair convenes the council on terms, payment rails, timing, controls, audit, or product wording." \
  "You are a corporate controller who has run AP and treasury at a 500-person company on Ramp. Check that payment terms, discount bases, ACH, RTP and card timing, statement cycles, late fees, buffers, approvals, segregation of duties, and the audit trail are realistic, and that no number or claim would embarrass the team in front of a finance professional or an auditor."
write_agent council-ramp-engineer "Read, Grep, Glob, Bash" \
  "Council reviewer acting as a Ramp staff engineer. Use when the chair convenes the council on architecture, code quality, data-model fit with Ramp Bill Pay, performance, or failure modes." \
  "You are a staff engineer on Ramp's Bill Pay and Treasury teams. Check readability (could a new hire follow it?), naming, test quality, determinism, performance on a small CPU, failure handling, offline behavior, and whether the data model and payload preview match Ramp's developer API (bill fields, payment_method enum, payment_date, hold and release). Ask: would I ship this behind a feature flag? You may run tests with .venv/bin/python; never modify files."
write_agent council-design "Read, Grep, Glob" \
  "Council reviewer acting as a product designer for finance tools. Use when the chair convenes the council on UI direction, screenshots, information hierarchy, or accessibility." \
  "You are a product designer who has shipped dense finance software. Review the design system file and the screenshots you are given (read the image files). Check hierarchy, density, alignment, number formatting (tabular figures, right-aligned money, consistent decimals), color semantics, empty, loading and error states, focus visibility, contrast, and anything that looks AI-generated (purple gradients, glassmorphism, emoji icons, cards inside cards, meaningless status dots)."
write_agent council-judge "Read, Grep, Glob" \
  "Council reviewer acting as a skeptical hackathon judge from Ramp engineering. Use when the chair convenes the council on novelty, claims, the demo path, README, or submission readiness." \
  "You are a Ramp engineer judging a student hackathon. Attack the premise, any overclaim about Ramp or competitors (Centime, C2FO, SAP Taulia, Billhop), any number that cannot be traced to data or the solver, and anything that would break or confuse in a 4-minute live demo. Name the simplest credible alternative and say whether Tempo clearly beats it. Score demo-readiness from 1 to 10."
ok "council-quant, council-controller, council-ramp-engineer, council-design, council-judge"

echo "== 8. Keep-going Stop hook (the session keeps working until PROGRESS.md says DONE or BLOCKED)"
mkdir -p .claude/hooks
cat > .claude/hooks/keep_going.py <<'PY'
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
PY
ok ".claude/hooks/keep_going.py"

echo "== 9. Project settings: Stop hook, ECC hooks minimal, GateGuard off"
python3.12 - <<'PY'
import json, pathlib
p = pathlib.Path(".claude/settings.json"); p.parent.mkdir(exist_ok=True)
s = json.loads(p.read_text()) if p.exists() else {}
s.setdefault("env", {}).update({"ECC_HOOK_PROFILE": "minimal", "ECC_GATEGUARD": "off", "ECC_CONTEXT_MONITOR_COST_WARNINGS": "off"})
stop = s.setdefault("hooks", {}).setdefault("Stop", [])
cmd = "python3 .claude/hooks/keep_going.py"
if not any(h.get("command") == cmd for entry in stop for h in entry.get("hooks", [])):
    stop.append({"hooks": [{"type": "command", "command": cmd}]})
p.write_text(json.dumps(s, indent=2) + "\n")
PY
ok ".claude/settings.json updated"

echo "== 10. Directive, CLAUDE.md pointer, .gitignore"
mkdir -p docs
cp "$DIRECTIVE" docs/BUILD_DIRECTIVE.md && ok "directive copied to docs/BUILD_DIRECTIVE.md"
cp "$0" tooling/setup_harness.sh 2>/dev/null && ok "this script saved to tooling/setup_harness.sh"
if ! grep -q "BUILD_DIRECTIVE" CLAUDE.md 2>/dev/null; then
cat >> CLAUDE.md <<'EOF'

## Tempo build (BBS x Ramp Hackathon, Round 2)
- Source of truth: docs/BUILD_DIRECTIVE.md. Read it fully at the start of every session and after every compaction.
- Then read PROGRESS.md and docs/DECISIONS.md and continue from the next unfinished step. Do not ask the humans for approval between phases.
- Use the project venv: .venv/bin/python, .venv/bin/pytest.
EOF
ok "CLAUDE.md pointer added"
fi
touch .gitignore
for line in ".env" ".tempo_local_model" ".venv/" "__pycache__/" ".pytest_cache/" ".ruff_cache/" "node_modules/" ".claude/skills/" ".agents/" ".claude/settings.local.json" ".claude/hooks/.keep_going_count" "test-results/" "playwright-report/"; do
  grep -qxF "$line" .gitignore || echo "$line" >> .gitignore
done
ok ".gitignore updated"

cat <<'EOF'

== Done. Next:
  1. Start a FRESH Claude Code session here (plugins, agents and hooks load at startup):
       ECC_HOOK_PROFILE=minimal ECC_GATEGUARD=off claude --model claude-opus-5-5 --permission-mode auto
  2. Inside Claude, type /plugin and confirm ecc, superpowers and frontend-design are enabled.
  3. Send this one message:
       Read docs/BUILD_DIRECTIVE.md in full and execute it end to end. We opt out of all brainstorming questions; the directive is the approved design.
  4. In the morning, after Claude's first push: render.com > sign in with GitHub > New > Blueprint > pick this repo > Apply.
     Paste the URL into PROGRESS.md under "Live URL". Every later push redeploys automatically.
EOF
