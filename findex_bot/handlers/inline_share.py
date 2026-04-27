from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    LinkPreviewOptions,
)

import findex_bot.runtime as runtime
from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import AdRepo
from findex_bot.utils.vacancy_utils import build_share_card, is_ad_shareable

logger = logging.getLogger(__name__)
router = Router()


def _parse_share_query(raw: str) -> Optional[int]:
    s = str(raw or "").strip()
    if not s:
        return None

    prefixes = ("share_ad_", "share:", "share ")
    for prefix in prefixes:
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
            break

    try:
        ad_id = int(s)
        return ad_id if ad_id > 0 else None
    except Exception:
        return None


@router.inline_query()
async def inline_share_handler(iq: InlineQuery):
    ad_id = _parse_share_query(iq.query or "")
    if not ad_id:
        return await iq.answer(
            results=[],
            cache_time=1,
            is_personal=True,
        )

    async with get_sessionmaker()() as session:
        repo = AdRepo(session)
        ad = await repo.get(int(ad_id))

    if not ad:
        return await iq.answer(
            results=[],
            cache_time=1,
            is_personal=True,
        )

    ok, _reason = is_ad_shareable(ad)
    if not ok:
        return await iq.answer(
            results=[],
            cache_time=1,
            is_personal=True,
        )

    bot_username = str(getattr(runtime, "BOT_USERNAME", "") or "").strip().lstrip("@")
    share_text = build_share_card(ad, bot_username)

    payload = ad.payload or {}
    role = str(getattr(ad, "role", "") or payload.get("role") or "employer").strip().lower()
    title = str(payload.get("title") or "Вакансия").strip()
    salary = str(payload.get("salary") or "").strip()
    location = str(payload.get("location") or "").strip()

    if role == "seeker":
        result_title = f"Поделиться анкетой: {title}"
    else:
        result_title = f"Поделиться вакансией: {title}"

    description_parts: list[str] = []
    if location:
        description_parts.append(location)
    if salary:
        description_parts.append(salary)
    result_description = " • ".join(description_parts) if description_parts else "Компактная карточка для пересылки"

    result = InlineQueryResultArticle(
        id=f"share_ad_{int(ad.id)}",
        title=result_title,
        description=result_description,
        input_message_content=InputTextMessageContent(
            message_text=share_text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        ),
    )

    try:
        await iq.answer(
            results=[result],
            cache_time=1,
            is_personal=True,
        )
    except Exception:
        logger.exception("inline share answer failed for ad_id=%s", ad_id)
        with logger.disabled:
            pass