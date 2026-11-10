"""Tempo HTTP API. Routes only; all logic lives in the `tempo` package."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Tempo", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for Render and the keep-warm workflow."""
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the single-page UI."""
    return FileResponse(STATIC_DIR / "index.html")
