# findex_bot/handlers/forms.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    TelegramObject,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.dispatcher.middlewares.base import BaseMiddleware

import findex_bot.runtime as runtime
from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import AdRepo
from findex_bot.utils.ui_utils import (
    safe_answer,
    employer_preview_keyboard,
    seeker_preview_keyboard,
    DAILY_FREE_LIMIT,
    is_unlimited_user,
    utc_day_key,
    utc_seconds_to_reset,
    format_hhmmss,
)
from findex_bot.utils.vacancy_utils import get_ad_text
from findex_bot.handlers.alerts import fire_alerts_on_publish

logger = logging.getLogger(__name__)
router = Router()


class SavedHintMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        return await handler(event, data)


# ---------------------------
# ✅ ДОП.ИНФО ДЛЯ МОДЕРАЦИИ
# ---------------------------
def _moderator_label(cb: CallbackQuery) -> str:
    u = cb.from_user
    if u and u.username:
        return f"@{u.username}"
    if u:
        return f"<code>{u.id}</code>"
    return "—"


def _publish_info_block(cb: CallbackQuery, public_url: str | None) -> str:
    url = public_url or "—"
    return f"\n\n✅ Опубликовано!\nМодератор: {_moderator_label(cb)}\nСсылка: {url}"


def _strip_publish_info(text: str) -> str:
    if not text:
        return text
    marker = "\n\n✅ Опубликовано!"
    if marker in text:
        return text.split(marker)[0]
    return text


# ---------------------------
# ✅ ЮЗЕР: сообщение “как на скрине” + кнопка повтор
# ---------------------------
def _republish_kb(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Повторить публикацию", callback_data=f"republish:{ad_id}")]
        ]
    )


def _counter_store() -> dict:
    store = getattr(runtime, "USER_PUB_COUNTER", None)
    if store is None or not isinstance(store, dict):
        store = {}
        runtime.USER_PUB_COUNTER = store
    return store


def _get_user_daily_counter(user_id: int) -> int:
    store = _counter_store()
    key = f"{int(user_id)}:{utc_day_key()}"
    try:
        return int(store.get(key, 0) or 0)
    except Exception:
        return 0


def _inc_user_daily_counter(user_id: int) -> int:
    store = _counter_store()
    key = f"{int(user_id)}:{utc_day_key()}"
    current = int(store.get(key, 0) or 0) + 1
    store[key] = current
    return current


def _user_publish_block(public_url: str | None, used_today: int, show_reset_timer: bool) -> str:
    url = public_url or "—"

    # отображение строго X/3 без “4/3”
    shown_used = min(max(0, int(used_today)), DAILY_FREE_LIMIT)

    block = (
        "\n\n✅ Опубликовано\n"
        f"🔗 Ссылка: {url}\n\n"
        f"📩 Бесплатные публикации сегодня (UTC): {shown_used}/{DAILY_FREE_LIMIT}\n"
    )

    if show_reset_timer:
        left = format_hhmmss(utc_seconds_to_reset())
        block += f"\n⏳ До сброса лимита (UTC): {left}\n"

    block += "\nℹ️ Чтобы создать новое объявление — нажми /start"
    return block


async def _send_user_published_message(cb: CallbackQuery, ad_id: int, public_url: str | None) -> None:
    async with get_sessionmaker()() as session:
        repo = AdRepo(session)
        ad = await repo.get(ad_id)
        if not ad:
            return

        payload = ad.payload or {}
        author_id = (payload or {}).get("author_id") or getattr(ad, "author_user_id", None)
        if not author_id:
            return
        author_id = int(author_id)

        author_username = (payload or {}).get("author_username")
        unlimited = is_unlimited_user(author_username)

        used_today = _inc_user_daily_counter(author_id)

        base_text = get_ad_text(ad)
        show_timer = (not unlimited) and (used_today >= DAILY_FREE_LIMIT)
        extra = _user_publish_block(public_url, used_today, show_timer)

        photo_file_id = payload.get("photo_file_id")
        video_file_id = payload.get("video_file_id")

        try:
            if video_file_id:
                caption = base_text + extra
                if len(caption) > 1024:
                    caption = caption[:1021] + "…"
                await cb.bot.send_video(author_id, video=video_file_id, caption=caption, reply_markup=_republish_kb(ad_id))
            elif photo_file_id:
                caption = base_text + extra
                if len(caption) > 1024:
                    caption = caption[:1021] + "…"
                await cb.bot.send_photo(author_id, photo=photo_file_id, caption=caption, reply_markup=_republish_kb(ad_id))
            else:
                await cb.bot.send_message(author_id, base_text + extra, reply_markup=_republish_kb(ad_id))
        except Exception:
            pass


# ---------------------------
# ✅ Репост: создать НОВЫЙ draft-клон и показать предпросмотр с кнопкой “Отправить на модерацию”
# ---------------------------
def _detect_role(payload: dict) -> str:
    role = (payload.get("role") or "").strip().lower()
    if role in ("employer", "seeker"):
        return role
    return "employer"


def _preview_keyboard_for_role(role: str, ad_id: int) -> InlineKeyboardMarkup:
    return seeker_preview_keyboard(ad_id) if role == "seeker" else employer_preview_keyboard(ad_id)


async def _send_preview_to_user(cb: CallbackQuery, ad_id: int, role: str, payload: dict, text: str) -> None:
    kb = _preview_keyboard_for_role(role, ad_id)

    photo_file_id = payload.get("photo_file_id")
    video_file_id = payload.get("video_file_id")

    try:
        if video_file_id:
            caption = text
            if len(caption) > 1024:
                caption = caption[:1021] + "…"
            await cb.bot.send_video(cb.from_user.id, video=video_file_id, caption=caption, reply_markup=kb)
            return

        if photo_file_id:
            caption = text
            if len(caption) > 1024:
                caption = caption[:1021] + "…"
            await cb.bot.send_photo(cb.from_user.id, photo=photo_file_id, caption=caption, reply_markup=kb)
            return

        await cb.bot.send_message(cb.from_user.id, text, reply_markup=kb)
    except Exception:
        try:
            await cb.bot.send_message(cb.from_user.id, text, reply_markup=kb)
        except Exception:
            pass


@router.callback_query(F.data.startswith("republish:"))
async def republish_to_user(callback: CallbackQuery):
    await safe_answer(callback)

    try:
        src_ad_id = int((callback.data or "").split(":")[1])
    except Exception:
        return await safe_answer(callback, "⚠️ Некорректные данные", alert=True)

    async with get_sessionmaker()() as session:
        repo = AdRepo(session)

        src = await repo.get(src_ad_id)
        if not src:
            return await safe_answer(callback, "❌ Объявление не найдено", alert=True)

        if getattr(src, "status", None) != "published":
            return await safe_answer(callback, "⚠️ Это объявление ещё не опубликовано", alert=True)

        src_payload = src.payload or {}
        role = _detect_role(src_payload)

        # ✅ создаём новый черновик
        new_ad = await repo.get_or_create_draft(author_user_id=callback.from_user.id, role=role)

        copy_payload: dict[str, Any] = {
            "role": role,
            "author_id": callback.from_user.id,
            "author_username": (callback.from_user.username or "").lstrip("@").strip() or None,
            "title": src_payload.get("title"),
            "salary": src_payload.get("salary"),
            "location": src_payload.get("location"),
            "contacts": src_payload.get("contacts"),
            "description": src_payload.get("description"),
            "photo_file_id": src_payload.get("photo_file_id"),
            "video_file_id": src_payload.get("video_file_id"),
        }
        if role == "seeker":
            copy_payload["schedule"] = src_payload.get("schedule")

        # чистим мету
        copy_payload["published"] = False
        copy_payload["on_moderation"] = False
        copy_payload["sent_to_moderation"] = False
        copy_payload["approved_by"] = None
        copy_payload["main_message_id"] = None
        copy_payload["main_channel_id"] = None
        copy_payload["moderation_chat_id"] = None
        copy_payload["moderation_message_id"] = None
        copy_payload["public_url"] = None

        await repo.patch_payload(new_ad.id, **copy_payload)
        await repo.set_status(new_ad.id, "draft")

        preview_text = get_ad_text(new_ad)
        await _send_preview_to_user(callback, new_ad.id, role, copy_payload, preview_text)

    return await safe_answer(callback, "✅ Предпросмотр создан. Нажми «Отправить на модерацию».", alert=True)


@router.callback_query(F.data.startswith("approve:"))
async def approve_ad(callback: CallbackQuery):
    await safe_answer(callback)

    try:
        ad_id = int((callback.data or "").split(":")[1])
    except Exception:
        return await safe_answer(callback, "⚠️ Некорректные данные", alert=True)

    channel_id = int(getattr(runtime, "MAIN_CHANNEL_ID", 0) or 0)
    channel_username = str(getattr(runtime, "CHANNEL_USERNAME", "") or "").lstrip("@").strip()

    if channel_id == 0:
        return await safe_answer(callback, "⚠️ MAIN_CHANNEL_ID не настроен", alert=True)

    async with get_sessionmaker()() as session:
        repo = AdRepo(session)
        ad = await repo.get(ad_id)
        if not ad:
            return await safe_answer(callback, "❌ Объявление не найдено", alert=True)

        if ad.status == "published":
            return await safe_answer(callback, "⚠️ Уже опубликовано", alert=True)

        payload = ad.payload or {}
        author_id = (payload or {}).get("author_id") or getattr(ad, "author_user_id", None)
        author_username = (payload or {}).get("author_username")

        # ✅ ЖЁСТКИЙ СТОП ЛИМИТА НА approve (защита от “4/3” навсегда)
        if author_id and (not is_unlimited_user(author_username)):
            published = _get_user_daily_counter(int(author_id))
            if published >= DAILY_FREE_LIMIT:
                left = format_hhmmss(utc_seconds_to_reset())
                warn = (
                    f"⛔ Лимит публикаций исчерпан ({published}/{DAILY_FREE_LIMIT}).\n"
                    f"До сброса (UTC): {left}"
                )

                # уведомление модератору
                try:
                    if callback.message:
                        if callback.message.caption is not None:
                            base = _strip_publish_info(callback.message.caption)
                            new_caption = base + f"\n\n{warn}"
                            if len(new_caption) > 1024:
                                new_caption = new_caption[:1021] + "…"
                            await callback.message.edit_caption(caption=new_caption, reply_markup=None)
                        else:
                            base = _strip_publish_info(callback.message.text or "")
                            await callback.message.edit_text(base + f"\n\n{warn}", reply_markup=None)
                except Exception:
                    pass

                # уведомление автору
                try:
                    await callback.bot.send_message(int(author_id), warn)
                except Exception:
                    pass

                return await safe_answer(callback, "⛔ Лимит исчерпан", alert=True)

        text = get_ad_text(ad)
        photo_file_id = payload.get("photo_file_id")
        video_file_id = payload.get("video_file_id")

        # 1) Публикация в канал
        try:
            if video_file_id:
                msg = await callback.bot.send_video(channel_id, video=video_file_id, caption=text)
            elif photo_file_id:
                msg = await callback.bot.send_photo(channel_id, photo=photo_file_id, caption=text)
            else:
                msg = await callback.bot.send_message(channel_id, text)
        except Exception:
            logger.exception("publish to channel failed")
            return await safe_answer(callback, "❌ Ошибка публикации в канал", alert=True)

        # 2) public_url
        public_url: Optional[str] = None
        if channel_username:
            public_url = f"https://t.me/{channel_username}/{msg.message_id}"

        # 3) фиксируем published + url + мету
        await repo.set_status(ad.id, "published")
        await repo.set_public_url(ad.id, public_url)
        await repo.patch_payload(
            ad.id,
            approved_by=callback.from_user.id if callback.from_user else None,
            main_message_id=msg.message_id,
            main_channel_id=channel_id,
            published=True,
            on_moderation=False,
            sent_to_moderation=False,
            public_url=public_url,
        )

        # 4) доп-инфо в сообщении модерации
        try:
            if callback.message:
                add = _publish_info_block(callback, public_url)
                if callback.message.caption is not None:
                    base = _strip_publish_info(callback.message.caption)
                    new_caption = base + add
                    if len(new_caption) > 1024:
                        new_caption = new_caption[:1021] + "…"
                    await callback.message.edit_caption(caption=new_caption, reply_markup=None)
                else:
                    base = _strip_publish_info(callback.message.text or "")
                    await callback.message.edit_text(base + add, reply_markup=None)
        except Exception:
            pass

        # 5) сообщение юзеру + кнопка republish (и таймер только после 3-й публикации)
        try:
            await _send_user_published_message(callback, ad.id, public_url)
        except Exception:
            pass

        # 6) алерты после публикации
        try:
            await fire_alerts_on_publish(callback.bot, ad, url=public_url)
        except Exception:
            logger.exception("alerts failed")

    return await safe_answer(callback, "✅ Опубликовано", alert=True)
