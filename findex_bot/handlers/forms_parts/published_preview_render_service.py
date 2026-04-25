from __future__ import annotations

from aiogram.types import LinkPreviewOptions

from findex_bot.utils.ui_utils import published_preview_kb, is_unlimited
from findex_bot.utils.vacancy_utils import get_ad_text


async def _send_published_preview_message(
    *,
    bot,
    chat_id: int,
    ad,
    public_url: str | None,
    published: int | None,
    unlimited: bool,
    collapsed: bool,
):
    from findex_bot.handlers.forms import (
        _build_user_published_text,
        _safe_trunc_4096,
        _safe_trunc_caption_1024,
        _get_primary_photo_id,
    )

    payload = ad.payload or {}
    ad_text = get_ad_text(ad)
    text = _build_user_published_text(
        ad_text=ad_text,
        public_url=public_url,
        published=published,
        unlimited=unlimited,
        collapsed=collapsed,
    )
    kb = published_preview_kb(int(ad.id), collapsed=collapsed)

    if collapsed:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=_safe_trunc_4096(text),
            reply_markup=kb,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return int(msg.message_id), False

    photo_file_id = _get_primary_photo_id(payload)
    video_file_id = payload.get("video_file_id")

    if video_file_id:
        msg = await bot.send_video(
            chat_id=chat_id,
            video=video_file_id,
            caption=_safe_trunc_caption_1024(text),
            reply_markup=kb,
        )
        return int(msg.message_id), True

    if photo_file_id:
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=photo_file_id,
            caption=_safe_trunc_caption_1024(text),
            reply_markup=kb,
        )
        return int(msg.message_id), True

    msg = await bot.send_message(
        chat_id=chat_id,
        text=_safe_trunc_4096(text),
        reply_markup=kb,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    return int(msg.message_id), False


async def _replace_published_preview_message(
    *,
    bot,
    ad,
    collapsed: bool,
    current_chat_id: int,
    current_message_id: int,
) -> tuple[int, bool]:
    from findex_bot.handlers.forms import _resolve_published_count

    payload = ad.payload or {}
    author_id = int(payload.get("author_id") or getattr(ad, "author_user_id", 0) or 0)
    author_username = payload.get("author_username")
    unlimited = is_unlimited(author_id, author_username)

    published_count = await _resolve_published_count(author_id, unlimited)
    public_url = getattr(ad, "public_url", None) or payload.get("public_url")

    try:
        await bot.delete_message(chat_id=int(current_chat_id), message_id=int(current_message_id))
    except Exception:
        pass

    return await _send_published_preview_message(
        bot=bot,
        chat_id=int(current_chat_id),
        ad=ad,
        public_url=public_url,
        published=published_count,
        unlimited=unlimited,
        collapsed=collapsed,
    )
