from __future__ import annotations

from typing import Any


def _norm(v: Any) -> str:
    if v is None:
        return "-"
    text = str(v).replace("\n", " ").replace("\r", " ").strip()
    return text[:200]


def log_event(logger, event: str, **fields: Any) -> None:
    payload = " ".join(
        f"{k}={_norm(v)}"
        for k, v in sorted(fields.items())
        if v is not None
    )
    if payload:
        logger.info("OBS event=%s %s", event, payload)
    else:
        logger.info("OBS event=%s", event)
