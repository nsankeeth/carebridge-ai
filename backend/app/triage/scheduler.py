"""In-process loop that runs the escalation sweep. One API process is assumed (single-host deployment)."""

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db import SessionLocal
from app.services import now
from app.triage import routing

log = logging.getLogger("triage.scheduler")
_task: asyncio.Task | None = None


def _tick() -> dict[str, int]:
    db = SessionLocal()
    try:
        counts = routing.sweep(db, now())
        db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _loop() -> None:
    interval = get_settings().scheduler_interval_seconds
    while True:
        try:
            counts = await run_in_threadpool(_tick)
            if any(counts.values()):
                log.info("escalation sweep %s", counts)
        except Exception:
            log.exception("escalation sweep failed")
        await asyncio.sleep(interval)


def start() -> None:
    global _task
    if get_settings().scheduler_enabled and _task is None:
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        _task = None
