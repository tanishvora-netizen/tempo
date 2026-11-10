PY ?= .venv/bin/python
PORT ?= 8000
TAILWIND := ./node_modules/.bin/tailwindcss

.PHONY: setup data cache precompute dev test lint format results e2e demo-video verify-live demo css vendor

setup:
	python3.12 -m venv .venv
	$(PY) -m pip install -r requirements-dev.txt
	$(PY) -m playwright install chromium

data:
	$(PY) scripts/generate_data.py

cache:
	$(PY) scripts/build_cache.py --concurrency 2

precompute:
	$(PY) scripts/precompute.py

dev:
	$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT) --reload

test:
	$(PY) -m pytest -m "not e2e"

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

results:
	$(PY) scripts/make_results.py

e2e:
	$(PY) -m pytest -m e2e tests/e2e

demo-video:
	$(PY) scripts/record_demo.py

verify-live:
	@test -n "$(URL)" || (echo "usage: make verify-live URL=https://..." && exit 2)
	$(PY) scripts/verify_live.py "$(URL)"

demo:
	TEMPO_PROVIDER=ollama $(PY) -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT)

css:
	$(TAILWIND) -i app/static/css/input.css -o app/static/css/app.css --minify

vendor:
	$(PY) scripts/vendor_assets.py
