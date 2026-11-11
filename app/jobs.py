"""Background jobs for custom what-if solves (final fix pass, section C).

Render's free instance has 0.1 CPU and 512 MB, so a custom solve can take tens of seconds. Instead of holding
an HTTP request open:
- POST /api/optimize enqueues a job and returns its id at once; the page polls GET /api/jobs/{id} every second.
- One solve runs at a time (a single worker thread). Later requests wait in line, and the page says so, so two
  solves never hold their scenario arrays in memory together.
- Results are cached by input hash: repeating a scenario returns a finished job instantly.
- The solver has a hard time limit; if it is reached, the best feasible plan found is returned and labeled.
"""

import gc
import hashlib
import json
import logging
import queue
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from tempo.forecast.simulate import WhatIf

log = logging.getLogger("tempo")
CACHE_SIZE = 64
JOBS_KEPT = 200
QUEUE_MAX = 60  # beyond this the server answers 503 instead of queueing forever


def input_key(what_if: WhatIf, overrides: dict) -> str:
    """Stable hash of everything a custom solve depends on (the committed data is fixed per deploy)."""
    payload = {
        "customer_id": what_if.delay_customer_id,
        "delay_days": what_if.delay_days,
        "shock_cents": what_if.shock_cents,
        "shock_day": what_if.shock_day,
        "overrides": sorted((k, repr(v)) for k, v in overrides.items()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class Job:
    id: str
    key: str
    what_if: WhatIf
    overrides: dict
    status: str = "queued"  # queued | running | done | error
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None
    cached: bool = False
    result: dict | None = None
    error: str | None = None

    def view(self, position: int) -> dict:
        now = time.monotonic()
        out = {
            "job_id": self.id,
            "status": self.status,
            "cached": self.cached,
            "position": position,  # jobs ahead of this one (0 when running or done)
            "waited_seconds": round((self.started_at or now) - self.created_at, 1),
            "elapsed_seconds": round((self.finished_at or now) - (self.started_at or now), 1)
            if self.started_at
            else 0.0,
        }
        if self.status == "done":
            out["result"] = self.result
        if self.status == "error":
            out["error"] = self.error
        return out


class QueueFull(Exception):
    pass


class JobRunner:
    """A single worker thread that runs solves one at a time, with an LRU cache of finished results."""

    def __init__(self, solve: Callable[[WhatIf, dict], dict]) -> None:
        self._solve = solve
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._order: list[str] = []  # waiting job ids, oldest first
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(target=self._run, name="tempo-solver", daemon=True)
        self._worker.start()

    def is_cached(self, what_if: WhatIf, overrides: dict) -> bool:
        with self._lock:
            return input_key(what_if, overrides) in self._cache

    def submit(self, what_if: WhatIf, overrides: dict) -> dict:
        key = input_key(what_if, overrides)
        with self._lock:
            job = Job(uuid.uuid4().hex[:12], key, what_if, dict(overrides))
            if key in self._cache:
                self._cache.move_to_end(key)
                job.status, job.cached, job.result = "done", True, self._cache[key]
                job.started_at = job.finished_at = time.monotonic()
            else:
                running_same = next(
                    (j for j in self._jobs.values() if j.key == key and j.status in ("queued", "running")),
                    None,
                )
                if running_same is not None:  # the same scenario is already on its way: share it
                    return running_same.view(self._position(running_same.id))
                if len(self._order) >= QUEUE_MAX:
                    raise QueueFull
                self._order.append(job.id)
                self._queue.put(job.id)
            self._remember(job)
            return job.view(self._position(job.id))

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.view(self._position(job_id))

    def _position(self, job_id: str) -> int:
        """How many jobs are ahead: the one running plus those queued earlier."""
        if job_id not in self._order:
            return 0
        running = any(j.status == "running" for j in self._jobs.values())
        return self._order.index(job_id) + (1 if running else 0)

    def _remember(self, job: Job) -> None:
        self._jobs[job.id] = job
        while len(self._jobs) > JOBS_KEPT:
            oldest = next(iter(self._jobs))
            if self._jobs[oldest].status in ("queued", "running"):
                break
            self._jobs.popitem(last=False)

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            with self._lock:
                job = self._jobs.get(job_id)
                if job_id in self._order:
                    self._order.remove(job_id)
                if job is None:
                    continue
                job.status, job.started_at = "running", time.monotonic()
            try:
                result = self._solve(job.what_if, job.overrides)
                with self._lock:
                    job.result, job.status = result, "done"
                    self._cache[job.key] = result
                    while len(self._cache) > CACHE_SIZE:
                        self._cache.popitem(last=False)
            except Exception:
                log.exception("live solve failed")
                with self._lock:
                    job.status, job.error = (
                        "error",
                        "The solver could not finish this scenario. Please retry.",
                    )
            finally:
                job.finished_at = time.monotonic()
                gc.collect()  # release the scenario arrays before the next job starts
