from __future__ import annotations

import contextlib
import logging
from typing import Any

from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, LinkPreviewOptions

logger = logging.getLogger(__name__)


async def _store_intro_message(
    redis: Any,
    user_id: int,
    ad_id: int,
    message_id: int,
    *,
    get_redis_fn,
    intro_key_template: str,
    pending_respond_ttl_min: int,
) -> None:
    r = get_redis_fn(redis)
    key = intro_key_template.format(user_id=int(user_id), ad_id=int(ad_id))
    await r.set(key, str(int(message_id)), ex=pending_respond_ttl_min * 60)


async def _load_intro_message(
    redis: Any,
    user_id: int,
    ad_id: int,
    *,
    get_redis_fn,
    intro_key_template: str,
) -> int | None:
    try:
        r = get_redis_fn(redis)
        key = intro_key_template.format(user_id=int(user_id), ad_id=int(ad_id))
        raw = await r.get(key)
        if not raw:
            return None

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")

        return int(str(raw).strip())
    except Exception:
        logger.exception("_load_intro_message failed user_id=%s ad_id=%s", user_id, ad_id)
        return None


async def _clear_intro_message(
    redis: Any,
    user_id: int,
    ad_id: int,
    *,
    get_redis_fn,
    intro_key_template: str,
) -> None:
    with contextlib.suppress(Exception):
        r = get_redis_fn(redis)
        key = intro_key_template.format(user_id=int(user_id), ad_id=int(ad_id))
        await r.delete(key)


async def _clear_all_intro_messages(
    redis: Any,
    user_id: int,
    *,
    get_redis_fn,
    intro_key_template: str,
) -> None:
    with contextlib.suppress(Exception):
        r = get_redis_fn(redis)
        pattern = intro_key_template.format(user_id=int(user_id), ad_id="*")

        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break


async def _upsert_intro_message(
    bot,
    redis: Any,
    user_id: int,
    ad_id: int,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    load_intro_message_fn,
    store_intro_message_fn,
    intro_kb_fn,
    get_redis_fn,
    intro_key_template: str,
    pending_respond_ttl_min: int,
):
    prev_msg_id = await load_intro_message_fn(
        redis,
        int(user_id),
        int(ad_id),
        get_redis_fn=get_redis_fn,
        intro_key_template=intro_key_template,
    )
    lp = LinkPreviewOptions(is_disabled=True)
    kb = reply_markup or intro_kb_fn(int(ad_id))

    if prev_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=int(user_id),
                message_id=int(prev_msg_id),
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
                link_preview_options=lp,
            )
            await store_intro_message_fn(
                redis,
                int(user_id),
                int(ad_id),
                int(prev_msg_id),
                get_redis_fn=get_redis_fn,
                intro_key_template=intro_key_template,
                pending_respond_ttl_min=pending_respond_ttl_min,
            )
            return int(prev_msg_id)
        except Exception as e:
            if "message is not modified" in str(e).lower():
                await store_intro_message_fn(
                    redis,
                    int(user_id),
                    int(ad_id),
                    int(prev_msg_id),
                    get_redis_fn=get_redis_fn,
                    intro_key_template=intro_key_template,
                    pending_respond_ttl_min=pending_respond_ttl_min,
                )
                return int(prev_msg_id)

            with contextlib.suppress(Exception):
                await bot.delete_message(chat_id=int(user_id), message_id=int(prev_msg_id))

    m = await bot.send_message(
        chat_id=int(user_id),
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
        link_preview_options=lp,
    )
    await store_intro_message_fn(
        redis,
        int(user_id),
        int(ad_id),
        int(m.message_id),
        get_redis_fn=get_redis_fn,
        intro_key_template=intro_key_template,
        pending_respond_ttl_min=pending_respond_ttl_min,
    )
    return int(m.message_id)


async def _upsert_service_message(
    bot,
    redis: Any,
    user_id: int,
    ad_id: int,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: ParseMode | None = ParseMode.HTML,
    load_intro_message_fn,
    store_intro_message_fn,
    get_redis_fn,
    intro_key_template: str,
    pending_respond_ttl_min: int,
) -> int:
    prev_msg_id = await load_intro_message_fn(
        redis,
        int(user_id),
        int(ad_id),
        get_redis_fn=get_redis_fn,
        intro_key_template=intro_key_template,
    )
    lp = LinkPreviewOptions(is_disabled=True)

    if prev_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=int(user_id),
                message_id=int(prev_msg_id),
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                link_preview_options=lp,
            )
            await store_intro_message_fn(
                redis,
                int(user_id),
                int(ad_id),
                int(prev_msg_id),
                get_redis_fn=get_redis_fn,
                intro_key_template=intro_key_template,
                pending_respond_ttl_min=pending_respond_ttl_min,
            )
            return int(prev_msg_id)

        except Exception as e:
            if "message is not modified" in str(e).lower():
                await store_intro_message_fn(
                    redis,
                    int(user_id),
                    int(ad_id),
                    int(prev_msg_id),
                    get_redis_fn=get_redis_fn,
                    intro_key_template=intro_key_template,
                    pending_respond_ttl_min=pending_respond_ttl_min,
                )
                return int(prev_msg_id)

            with contextlib.suppress(Exception):
                await bot.delete_message(chat_id=int(user_id), message_id=int(prev_msg_id))

    m = await bot.send_message(
        chat_id=int(user_id),
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        link_preview_options=lp,
    )

    await store_intro_message_fn(
        redis,
        int(user_id),
        int(ad_id),
        int(m.message_id),
        get_redis_fn=get_redis_fn,
        intro_key_template=intro_key_template,
        pending_respond_ttl_min=pending_respond_ttl_min,
    )
    return int(m.message_id)
