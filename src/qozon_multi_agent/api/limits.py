"""Local durable counters, or mandatory private Cloudflare edge admission."""

import asyncio
from contextlib import closing
from functools import lru_cache
import hashlib
import hmac
from pathlib import Path
import sqlite3
import time

from fastapi import HTTPException, Request

from qozon_multi_agent.core.config import get_settings


class QuestionLimitReached(Exception):
    def __init__(self, code: str, retry_after: int):
        self.code, self.retry_after = code, retry_after
        super().__init__(code)


class QuestionLimits:
    def __init__(self, path: Path, key: str, per_minute: int, per_day: int):
        if len(key) < 32:
            raise ValueError("question_limit_key_required")
        self.path, self.key = path, key.encode()
        self.per_minute, self.per_day = per_minute, per_day
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=2)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (scope TEXT, client TEXT, expires INTEGER, "
                       "total INTEGER NOT NULL, PRIMARY KEY(scope, client))")

    def admit(self, client: str, *, now: float | None = None) -> None:
        """Reserve before retrieval/generation; failures and cancellations keep the slot."""
        timestamp = int(time.time() if now is None else now)
        minute_end = (timestamp // 60 + 1) * 60
        day_end = (timestamp // 86400 + 1) * 86400
        # No question text or raw IP is written to disk. Include the day so hashes rotate.
        identity = hmac.new(self.key, f"{timestamp // 86400}:{client}".encode(), hashlib.sha256).hexdigest()
        counters = [(f"minute:{timestamp // 60}", identity, minute_end, self.per_minute, "question_rate_limited"),
                    (f"day:{timestamp // 86400}", "all", day_end, self.per_day, "daily_question_limit_reached")]
        db = sqlite3.connect(self.path, timeout=2)
        try:
            # Serialize check + increment, including across processes on this same disk.
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM requests WHERE expires <= ?", (timestamp,))
            for scope, owner, expires, maximum, code in counters:
                row = db.execute("SELECT total FROM requests WHERE scope=? AND client=?", (scope, owner)).fetchone()
                if row and row[0] >= maximum:
                    raise QuestionLimitReached(code, max(1, expires - timestamp))
            for scope, owner, expires, _, _ in counters:
                db.execute("INSERT INTO requests VALUES (?, ?, ?, 1) "
                           "ON CONFLICT(scope, client) DO UPDATE SET total=total+1", (scope, owner, expires))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


@lru_cache
def configured_limits() -> QuestionLimits | None:
    settings = get_settings()
    if settings.question_limits_backend == "cloudflare":
        if not settings.question_limits_enabled or not settings.question_limit_key:
            raise ValueError("cloudflare_admission_required")
        return None
    if not settings.question_limits_enabled:
        return None
    if not settings.question_limit_key:
        raise ValueError("question_limit_key_required")
    return QuestionLimits(settings.question_limits_database, settings.question_limit_key.get_secret_value(),
                          settings.questions_per_minute, settings.questions_per_day)


def _admit(client: str) -> None:
    limits = configured_limits()
    if limits is not None:
        limits.admit(client)


async def admit_question(request: Request) -> None:
    """Require edge admission on Cloudflare; use trusted ASGI identity locally."""
    try:
        settings = get_settings()
        if settings.question_limits_backend == "cloudflare":
            if (not settings.question_limits_enabled or not settings.question_limit_key
                    or not hmac.compare_digest(
                        request.headers.get("X-Qozon-Admission", "").encode(),
                        settings.question_limit_key.get_secret_value().encode())):
                raise ValueError("cloudflare_admission_required")
            return
        await asyncio.to_thread(_admit, request.client.host if request.client else "unknown")
    except QuestionLimitReached as error:
        raise HTTPException(status_code=429, headers={"Retry-After": str(error.retry_after), "Cache-Control": "no-store"},
                            detail={"code": error.code, "message": "Question limit reached. Please try again later."}) from None
    except Exception:
        raise HTTPException(status_code=503, detail={"code": "question_limits_unavailable",
                                                    "message": "Question answering is temporarily unavailable."}) from None
