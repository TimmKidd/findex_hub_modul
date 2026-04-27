from __future__ import annotations

import logging
import findex_bot.runtime as runtime

logger = logging.getLogger(__name__)

UI_SURFACE_KEY = "ui:surface:{user_id}"
UI_SURFACE_TTL_SEC = 3600

async def enter_surface(user_id: int, surface: str) -> None:
    r = getattr(runtime, "REDIS", None)
    if r is None:
        return
    await r.set(UI_SURFACE_KEY.format(user_id=int(user_id)), str(surface), ex=UI_SURFACE_TTL_SEC)
    logger.info("ui_surface(shadow): enter user_id=%s surface=%s", user_id, surface)

async def clear_surface(user_id: int) -> None:
    r = getattr(runtime, "REDIS", None)
    if r is None:
        return
    await r.delete(UI_SURFACE_KEY.format(user_id=int(user_id)))
    logger.info("ui_surface(shadow): clear user_id=%s", user_id)

async def get_surface(user_id: int) -> str | None:
    r = getattr(runtime, "REDIS", None)
    if r is None:
        return None
    v = await r.get(UI_SURFACE_KEY.format(user_id=int(user_id)))
    if not v:
        return None
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="ignore") or None
        except Exception:
            return None
    return str(v) or None
