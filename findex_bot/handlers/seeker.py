# findex_bot/handlers/seeker.py
from __future__ import annotations

import logging
import os
from typing import Optional, Any

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

import findex_bot.runtime as runtime
from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import AdRepo
from findex_bot.states.vacancies import SeekerForm
from findex_bot.utils.vacancy_utils import get_ad_text
from findex_bot.utils.validators import (
    validate_required,
    validate_description,
    validate_salary,
    validate_location_letters_only,
    validate_contacts,
    validate_no_profanity,
    normalize_title,
    normalize_sentence,
)
from findex_bot.utils.ui_utils import (
    safe_answer,
    send_saved_hint,
    moderation_keyboard,
    seeker_media_choice_kb,
    media_confirm_kb,
    sent_to_moderation_stub_kb,  # ✅
    NOOP_CALLBACK,               # ✅
    # ✅ лимиты
    DAILY_FREE_LIMIT,
    is_unlimited_user,
    utc_day_key,
    utc_seconds_to_reset,
    format_hhmmss,
)

logger = logging.getLogger(__name__)
router = Router()

K_PENDING_MEDIA = "pending_media"
K_EDIT_MODE = "edit_mode"
K_PREVIEW_MSG_ID = "preview_msg_id"
K_PREVIEW_IS_MEDIA = "preview_is_media"


@router.callback_query(F.data == NOOP_CALLBACK)
async def _noop(cb: CallbackQuery):
    await safe_answer(cb)


def _parse_id(cbdata: str) -> int:
    return int((cbdata or "").split(":")[1])


def _get_moderation_chat_id() -> int:
    val = getattr(runtime, "MODERATION_CHAT_ID", None)
    if val:
        return int(val)

    cfg = getattr(runtime, "CONFIG", None)
    if cfg is not None and getattr(cfg, "moderation_chat_id", 0):
        return int(cfg.moderation_chat_id)

    envv = os.getenv("MODERATION_CHAT_ID")
    if envv:
        return int(envv)

    raise RuntimeError("MODERATION_CHAT_ID is not configured")


def _get_thread_vacancies() -> int:
    val = getattr(runtime, "THREAD_VACANCIES", None)
    try:
        v = int(val or 0)
    except Exception:
        v = 0
    if v:
        return v

    envv = os.getenv("THREAD_VACANCIES")
    try:
        return int(envv or 0)
    except Exception:
        return 0


def _moderation_user_footer(cb: CallbackQuery) -> str:
    u = cb.from_user
    uname = f"@{u.username}" if u.username else "—"
    full = " ".join([x for x in [u.first_name, u.last_name] if x]) or "—"

    return (
        "\n\n"
        f"Автор: {uname}\n"
        f"Telegram ID: <code>{u.id}</code>\n"
        f"Имя: {full}"
    )


async def _get_ad_id(state: FSMContext) -> Optional[int]:
    data = await state.get_data()
    ad_id = data.get("ad_id")
    try:
        return int(ad_id) if ad_id is not None else None
    except Exception:
        return None


def _is_edit_mode(data: dict) -> bool:
    return bool(data.get(K_EDIT_MODE))


async def _need_restart(message_or_cb: Message | CallbackQuery) -> None:
    text = "⚠️ Сессия сбилась. Нажми /start."
    try:
        if isinstance(message_or_cb, Message):
            await message_or_cb.answer(text)
        else:
            await safe_answer(message_or_cb, text, alert=True)
            if message_or_cb.message:
                await message_or_cb.message.answer(text)
            else:
                await message_or_cb.bot.send_message(message_or_cb.from_user.id, text)
    except Exception:
        pass


def _prompt_title() -> str:
    return "Укажи 👤 должность.\n\nПример: Бариста, Официант, Администратор"


def _prompt_schedule() -> str:
    return "Укажи 🕒 график.\n\nПример: 5/2, 2/2, Сменный, Гибкий, Удалёнка"


def _prompt_salary() -> str:
    return "Укажи 💲 зарплатные ожидания.\n\nПример: от 80 000, 120 000, по договорённости"


def _prompt_location() -> str:
    return "Укажи 📍 локацию.\n\nПример: Москва, Химки, ЦАО / СПБ, Приморский"


def _prompt_contacts() -> str:
    return (
        "Укажи 📞 контакты.\n\n"
        "ℹ️ Подсказка по контактам:\n"
        "• Telegram: @username\n"
        "• Телефон: +7 999 123-45-67\n"
        "• Email: name@mail.com\n"
        "• Любой удобный способ связи"
    )


def _prompt_about() -> str:
    return "Укажи 📝 о себе.\n\nПример: опыт, навыки, чем полезен, условия (до 2000 символов)"


def _published_today(user_id: int) -> int:
    store = getattr(runtime, "USER_PUB_COUNTER", None)
    if store is None or not isinstance(store, dict):
        return 0
    key = f"{int(user_id)}:{utc_day_key()}"
    try:
        return int(store.get(key, 0) or 0)
    except Exception:
        return 0


def _limit_block_text(published: int) -> str:
    left = format_hhmmss(utc_seconds_to_reset())
    return (
        f"⛔ Дневной лимит публикаций исчерпан ({published}/{DAILY_FREE_LIMIT}).\n"
        f"До сброса (UTC): {left}"
    )


def _seeker_preview_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Должность", callback_data=f"seek_edit_title:{ad_id}"),
                InlineKeyboardButton(text="🕒 График", callback_data=f"seek_edit_schedule:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="💲 Зарплата", callback_data=f"seek_edit_salary:{ad_id}"),
                InlineKeyboardButton(text="📍 Локация", callback_data=f"seek_edit_location:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="📞 Контакты", callback_data=f"seek_edit_contacts:{ad_id}"),
                InlineKeyboardButton(text="📝 О себе", callback_data=f"seek_edit_about:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="🖼 Фото", callback_data=f"seek_edit_media:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="✅ Отправить на модерацию", callback_data=f"send_seeker:{ad_id}"),
            ],
        ]
    )


async def _upsert_preview(bot, chat_id: int, state: FSMContext, ad_id: int) -> None:
    data = await state.get_data()
    prev_msg_id = data.get(K_PREVIEW_MSG_ID)
    prev_is_media = bool(data.get(K_PREVIEW_IS_MEDIA))

    async with get_sessionmaker()() as session:
        ad = await AdRepo(session).get(ad_id)
        if not ad:
            return
        payload = ad.payload or {}
        text = get_ad_text(ad)
        photo_id = payload.get("photo_file_id")

    has_media = bool(photo_id)

    try:
        if prev_msg_id:
            if has_media:
                if prev_is_media:
                    await bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=int(prev_msg_id),
                        caption=text,
                        reply_markup=_seeker_preview_keyboard(ad_id),
                    )
                    await state.update_data(**{K_PREVIEW_IS_MEDIA: True})
                    return
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=int(prev_msg_id))
                except Exception:
                    pass
            else:
                if not prev_is_media:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=int(prev_msg_id),
                        text=text,
                        reply_markup=_seeker_preview_keyboard(ad_id),
                    )
                    await state.update_data(**{K_PREVIEW_IS_MEDIA: False})
                    return
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=int(prev_msg_id))
                except Exception:
                    pass

        if has_media:
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=photo_id,
                caption=text,
                reply_markup=_seeker_preview_keyboard(ad_id),
            )
            await state.update_data(**{K_PREVIEW_MSG_ID: msg.message_id, K_PREVIEW_IS_MEDIA: True})
        else:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=_seeker_preview_keyboard(ad_id),
            )
            await state.update_data(**{K_PREVIEW_MSG_ID: msg.message_id, K_PREVIEW_IS_MEDIA: False})

    except Exception:
        if has_media:
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=photo_id,
                caption=text,
                reply_markup=_seeker_preview_keyboard(ad_id),
            )
            await state.update_data(**{K_PREVIEW_MSG_ID: msg.message_id, K_PREVIEW_IS_MEDIA: True})
        else:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=_seeker_preview_keyboard(ad_id),
            )
            await state.update_data(**{K_PREVIEW_MSG_ID: msg.message_id, K_PREVIEW_IS_MEDIA: False})


async def _send_fresh_preview(bot, chat_id: int, state: FSMContext, ad_id: int) -> None:
    data = await state.get_data()
    old_msg_id = data.get(K_PREVIEW_MSG_ID)

    if old_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=int(old_msg_id))
        except Exception:
            pass

    async with get_sessionmaker()() as session:
        ad = await AdRepo(session).get(ad_id)
        if not ad:
            return
        payload = ad.payload or {}
        text = get_ad_text(ad)
        photo_id = payload.get("photo_file_id")

    try:
        if photo_id:
            msg = await bot.send_photo(chat_id=chat_id, photo=photo_id, caption=text, reply_markup=_seeker_preview_keyboard(ad_id))
            await state.update_data(**{K_PREVIEW_MSG_ID: msg.message_id, K_PREVIEW_IS_MEDIA: True})
        else:
            msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=_seeker_preview_keyboard(ad_id))
            await state.update_data(**{K_PREVIEW_MSG_ID: msg.message_id, K_PREVIEW_IS_MEDIA: False})
    except Exception:
        pass


async def _after_field_saved(message: Message, state: FSMContext, ad_id: int, next_state, next_prompt: str) -> None:
    data = await state.get_data()

    if _is_edit_mode(data):
        await send_saved_hint(message)
        await state.update_data(**{K_EDIT_MODE: False})
        await state.set_state(SeekerForm.preview)
        await _send_fresh_preview(message.bot, message.chat.id, state, ad_id)
        return

    await state.set_state(next_state)
    await message.answer(next_prompt)


@router.callback_query(F.data == "vac_seeker")
async def seeker_entry(cb: CallbackQuery, state: FSMContext):
    await safe_answer(cb)
    await state.clear()

    async with get_sessionmaker()() as session:
        repo = AdRepo(session)
        ad = await repo.get_or_create_draft(author_user_id=cb.from_user.id, role="seeker")
        await repo.patch_payload(ad.id, role="seeker", author_id=cb.from_user.id)

    await state.update_data(ad_id=ad.id, preview_msg_id=None, preview_is_media=False, edit_mode=False)
    await state.set_state(SeekerForm.title)

    if cb.message:
        await cb.message.answer(_prompt_title())
    else:
        await cb.bot.send_message(cb.from_user.id, _prompt_title())


@router.message(SeekerForm.title)
async def seek_title(message: Message, state: FSMContext):
    ad_id = await _get_ad_id(state)
    if not ad_id:
        await _need_restart(message)
        return

    val = (message.text or "").strip()
    err = validate_required(val, "Должность") or validate_no_profanity(val)
    if err:
        await message.answer(err)
        return

    val = normalize_title(val)
    async with get_sessionmaker()() as session:
        await AdRepo(session).patch_payload(ad_id, title=val)

    await _after_field_saved(message, state, ad_id, SeekerForm.schedule, _prompt_schedule())


@router.message(SeekerForm.schedule)
async def seek_schedule(message: Message, state: FSMContext):
    ad_id = await _get_ad_id(state)
    if not ad_id:
        await _need_restart(message)
        return

    val = (message.text or "").strip()
    err = validate_required(val, "График") or validate_no_profanity(val)
    if err:
        await message.answer(err)
        return

    async with get_sessionmaker()() as session:
        await AdRepo(session).patch_payload(ad_id, schedule=val)

    await _after_field_saved(message, state, ad_id, SeekerForm.salary, _prompt_salary())


@router.message(SeekerForm.salary)
async def seek_salary(message: Message, state: FSMContext):
    ad_id = await _get_ad_id(state)
    if not ad_id:
        await _need_restart(message)
        return

    val = (message.text or "").strip()
    err = validate_required(val, "Зарплата") or validate_no_profanity(val) or validate_salary(val)
    if err:
        await message.answer(err)
        return

    async with get_sessionmaker()() as session:
        await AdRepo(session).patch_payload(ad_id, salary=val)

    await _after_field_saved(message, state, ad_id, SeekerForm.location, _prompt_location())


@router.message(SeekerForm.location)
async def seek_location(message: Message, state: FSMContext):
    ad_id = await _get_ad_id(state)
    if not ad_id:
        await _need_restart(message)
        return

    val = (message.text or "").strip()
    err = validate_required(val, "Локация") or validate_no_profanity(val) or validate_location_letters_only(val)
    if err:
        await message.answer(err)
        return

    val = normalize_title(val)
    async with get_sessionmaker()() as session:
        await AdRepo(session).patch_payload(ad_id, location=val)

    await _after_field_saved(message, state, ad_id, SeekerForm.contacts, _prompt_contacts())


@router.message(SeekerForm.contacts)
async def seek_contacts(message: Message, state: FSMContext):
    ad_id = await _get_ad_id(state)
    if not ad_id:
        await _need_restart(message)
        return

    val = (message.text or "").strip()
    err = validate_required(val, "Контакты") or validate_no_profanity(val) or validate_contacts(val)
    if err:
        await message.answer(err)
        return

    async with get_sessionmaker()() as session:
        await AdRepo(session).patch_payload(ad_id, contacts=val)

    await _after_field_saved(message, state, ad_id, SeekerForm.description, _prompt_about())


@router.message(SeekerForm.description)
async def seek_about(message: Message, state: FSMContext):
    ad_id = await _get_ad_id(state)
    if not ad_id:
        await _need_restart(message)
        return

    val = (message.text or "").strip()
    err = validate_required(val, "О себе") or validate_no_profanity(val) or validate_description(val)
    if err:
        await message.answer(err)
        return

    val = normalize_sentence(val)
    async with get_sessionmaker()() as session:
        await AdRepo(session).patch_payload(ad_id, description=val)

    data = await state.get_data()
    if _is_edit_mode(data):
        await send_saved_hint(message)
        await state.update_data(**{K_EDIT_MODE: False})
        await state.set_state(SeekerForm.preview)
        await _send_fresh_preview(message.bot, message.chat.id, state, ad_id)
        return

    await state.set_state(SeekerForm.media_choice)
    await message.answer("Добавить 🖼 фото?\n\nФото не обязательно.", reply_markup=seeker_media_choice_kb())


@router.callback_query(F.data == "seek_media_add")
async def seek_media_add(cb: CallbackQuery, state: FSMContext):
    await safe_answer(cb)
    await state.set_state(SeekerForm.media_wait)
    if cb.message:
        await cb.message.answer("Пришли ОДНО фото одним сообщением.")
    else:
        await cb.bot.send_message(cb.from_user.id, "Пришли ОДНО фото одним сообщением.")


@router.callback_query(F.data == "seek_media_skip")
async def seek_media_skip(cb: CallbackQuery, state: FSMContext):
    await safe_answer(cb)
    ad_id = await _get_ad_id(state)
    if not ad_id:
        await _need_restart(cb)
        return

    async with get_sessionmaker()() as session:
        await AdRepo(session).patch_payload(ad_id, photo_file_id=None)

    await state.set_state(SeekerForm.preview)
    await _upsert_preview(cb.bot, cb.from_user.id, state, ad_id)


@router.message(SeekerForm.media_wait, F.photo)
async def seek_media_wait_photo(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(**{K_PENDING_MEDIA: {"type": "photo", "file_id": file_id}})
    await state.set_state(SeekerForm.media_confirm)
    await message.answer("Принял файл. Подтверждаешь?", reply_markup=media_confirm_kb("seek_media_confirm"))


@router.message(SeekerForm.media_wait)
async def seek_media_wait_bad(message: Message):
    await message.answer("Нужно отправить ОДНО фото (не текст и не видео).")


@router.callback_query(F.data.startswith("seek_media_confirm:"))
async def seek_media_confirm(cb: CallbackQuery, state: FSMContext):
    await safe_answer(cb)
    action = (cb.data or "").split(":")[1]

    ad_id = await _get_ad_id(state)
    if not ad_id:
        await _need_restart(cb)
        return

    data = await state.get_data()
    pending = data.get(K_PENDING_MEDIA)

    if action == "retry":
        await state.update_data(**{K_PENDING_MEDIA: None})
        await state.set_state(SeekerForm.media_wait)
        if cb.message:
            await cb.message.answer("Ок. Пришли другое фото (одно).")
        else:
            await cb.bot.send_message(cb.from_user.id, "Ок. Пришли другое фото (одно).")
        return

    if action == "delete":
        async with get_sessionmaker()() as session:
            await AdRepo(session).patch_payload(ad_id, photo_file_id=None)

        await state.update_data(**{K_PENDING_MEDIA: None})
        await send_saved_hint(cb)
        await state.set_state(SeekerForm.preview)
        await _upsert_preview(cb.bot, cb.from_user.id, state, ad_id)
        return

    if not pending or not isinstance(pending, dict) or not pending.get("file_id"):
        await safe_answer(cb, "⚠️ Не вижу фото. Пришли ещё раз.", alert=True)
        await state.set_state(SeekerForm.media_wait)
        return

    fid = pending.get("file_id")
    async with get_sessionmaker()() as session:
        await AdRepo(session).patch_payload(ad_id, photo_file_id=fid)

    await state.update_data(**{K_PENDING_MEDIA: None})
    await send_saved_hint(cb)
    await state.set_state(SeekerForm.preview)
    await _upsert_preview(cb.bot, cb.from_user.id, state, ad_id)


async def _set_edit_state(cb: CallbackQuery, state: FSMContext, ad_id: int, next_state: Any):
    await safe_answer(cb)
    data = await state.get_data()
    keep_preview_msg_id = data.get(K_PREVIEW_MSG_ID)
    keep_preview_is_media = data.get(K_PREVIEW_IS_MEDIA)

    await state.clear()
    await state.update_data(
        ad_id=ad_id,
        edit_mode=True,
        preview_msg_id=keep_preview_msg_id,
        preview_is_media=keep_preview_is_media,
    )
    await state.set_state(next_state)


@router.callback_query(F.data.startswith("seek_edit_title:"))
async def seek_edit_title(cb: CallbackQuery, state: FSMContext):
    ad_id = _parse_id(cb.data)
    await _set_edit_state(cb, state, ad_id, SeekerForm.title)
    await cb.message.answer(_prompt_title())


@router.callback_query(F.data.startswith("seek_edit_schedule:"))
async def seek_edit_schedule(cb: CallbackQuery, state: FSMContext):
    ad_id = _parse_id(cb.data)
    await _set_edit_state(cb, state, ad_id, SeekerForm.schedule)
    await cb.message.answer(_prompt_schedule())


@router.callback_query(F.data.startswith("seek_edit_salary:"))
async def seek_edit_salary(cb: CallbackQuery, state: FSMContext):
    ad_id = _parse_id(cb.data)
    await _set_edit_state(cb, state, ad_id, SeekerForm.salary)
    await cb.message.answer(_prompt_salary())


@router.callback_query(F.data.startswith("seek_edit_location:"))
async def seek_edit_location(cb: CallbackQuery, state: FSMContext):
    ad_id = _parse_id(cb.data)
    await _set_edit_state(cb, state, ad_id, SeekerForm.location)
    await cb.message.answer(_prompt_location())


@router.callback_query(F.data.startswith("seek_edit_contacts:"))
async def seek_edit_contacts(cb: CallbackQuery, state: FSMContext):
    ad_id = _parse_id(cb.data)
    await _set_edit_state(cb, state, ad_id, SeekerForm.contacts)
    await cb.message.answer(_prompt_contacts())


@router.callback_query(F.data.startswith("seek_edit_about:"))
async def seek_edit_about(cb: CallbackQuery, state: FSMContext):
    ad_id = _parse_id(cb.data)
    await _set_edit_state(cb, state, ad_id, SeekerForm.description)
    await cb.message.answer(_prompt_about())


@router.callback_query(F.data.startswith("seek_edit_description:"))
async def seek_edit_description_compat(cb: CallbackQuery, state: FSMContext):
    ad_id = _parse_id(cb.data)
    await _set_edit_state(cb, state, ad_id, SeekerForm.description)
    await cb.message.answer(_prompt_about())


@router.callback_query(F.data.startswith("seek_edit_media:"))
async def seek_edit_media(cb: CallbackQuery, state: FSMContext):
    ad_id = _parse_id(cb.data)
    await safe_answer(cb)

    data = await state.get_data()
    keep_preview_msg_id = data.get(K_PREVIEW_MSG_ID)
    keep_preview_is_media = data.get(K_PREVIEW_IS_MEDIA)

    await state.clear()
    await state.update_data(
        ad_id=ad_id,
        edit_mode=True,
        preview_msg_id=keep_preview_msg_id,
        preview_is_media=keep_preview_is_media,
    )
    await state.set_state(SeekerForm.media_choice)

    await cb.message.answer("Добавить 🖼 фото?\n\nФото не обязательно.", reply_markup=seeker_media_choice_kb())


@router.callback_query(F.data.startswith("send_seeker:"))
async def seek_send(cb: CallbackQuery):
    await safe_answer(cb)
    ad_id = _parse_id(cb.data)

    # ✅ ЛИМИТ: считаем по факту публикаций (approve), но блокируем 4-ю попытку отправки на модерацию
    if not is_unlimited_user(getattr(cb.from_user, "username", None)):
        published = _published_today(int(cb.from_user.id))
        if published >= DAILY_FREE_LIMIT:
            warn = _limit_block_text(published)
            await safe_answer(cb, warn, alert=True)
            try:
                if cb.message:
                    await cb.message.answer(warn)
                else:
                    await cb.bot.send_message(cb.from_user.id, warn)
            except Exception:
                pass
            return

    async with get_sessionmaker()() as session:
        repo = AdRepo(session)
        ad = await repo.get(ad_id)
        if not ad:
            await safe_answer(cb, "❌ Не найдено", alert=True)
            return

        if ad.status == "pending":
            await safe_answer(cb, "⏳ Уже на модерации", alert=True)
            return
        if ad.status == "published":
            await safe_answer(cb, "⚠️ Уже опубликовано", alert=True)
            return

        mod_chat_id = _get_moderation_chat_id()
        thread_id = _get_thread_vacancies()

        payload = ad.payload or {}
        base_text = get_ad_text(ad)
        text = base_text + _moderation_user_footer(cb)

        photo_id = payload.get("photo_file_id")

        send_kwargs = {}
        if thread_id:
            send_kwargs["message_thread_id"] = thread_id

        if photo_id:
            msg = await cb.bot.send_photo(
                mod_chat_id,
                photo=photo_id,
                caption=text,
                reply_markup=moderation_keyboard(ad_id),
                **send_kwargs,
            )
        else:
            msg = await cb.bot.send_message(
                mod_chat_id,
                text,
                reply_markup=moderation_keyboard(ad_id),
                **send_kwargs,
            )

        await repo.set_status(ad_id, "pending")
        await repo.patch_payload(
            ad_id,
            moderation_chat_id=msg.chat.id,
            moderation_message_id=msg.message_id,
            author_id=cb.from_user.id,
            role="seeker",
        )

    # ✅ никаких отдельных сообщений — только заглушка на предпросмотре + lock
    try:
        if cb.message:
            try:
                await cb.message.edit_reply_markup(reply_markup=sent_to_moderation_stub_kb())
            except Exception:
                pass

            store = getattr(runtime, "PUBLISHED_PREVIEW_MESSAGES", None)
            if store is None or not isinstance(store, dict):
                store = {}
                runtime.PUBLISHED_PREVIEW_MESSAGES = store

            store[(int(cb.message.chat.id), int(cb.message.message_id))] = "moderation"
    except Exception:
        pass

    await safe_answer(cb, "✅ Отправлено на модерацию", alert=True)
