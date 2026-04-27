from __future__ import annotations

from typing import Any


def extract_preview_coords_from_payload(payload: dict[str, Any] | None) -> tuple[int, int, bool]:
    p = payload or {}
    try:
        chat_id = int(p.get("preview_chat_id") or 0)
        msg_id = int(p.get("preview_message_id") or 0)
        is_media = bool(p.get("preview_is_media") or False)
        return chat_id, msg_id, is_media
    except Exception:
        return 0, 0, False


def extract_preview_coords_fallback_runtime(ad_id: int, *, runtime_module) -> tuple[int, int, bool]:
    pending = getattr(runtime_module, "ADS_PENDING", None)
    if not pending or not isinstance(pending, dict):
        return 0, 0, False

    info = pending.get(int(ad_id))
    if not info or not isinstance(info, dict):
        return 0, 0, False

    try:
        chat_id = int(info.get("preview_chat_id") or 0)
        msg_id = int(info.get("preview_message_id") or 0)
        is_media = bool(info.get("preview_is_media"))
        return chat_id, msg_id, is_media
    except Exception:
        return 0, 0, False
