# findex_bot/handlers/alerts.py
from __future__ import annotations

import uuid
import logging
from typing import Any, Optional, Iterable

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import findex_bot.runtime as runtime

logger = logging.getLogger(__name__)
router = Router()

# ---------------------------
# FSM
# ---------------------------
class AlertFSM(StatesGroup):
    target = State()    # "seek" | "emp"
    position = State()  # keywords
    location = State()  # optional


# ---------------------------
# storage (in-memory, MVP)
# Поддерживаем оба варианта:
# - runtime.ALERTS_STORE (как в bot.py)
# - runtime.ALERTS (старый)
#
# store[user_id] = list[alert]
# alert = {id, target, keywords[], location?}
# ---------------------------
def _alerts_store() -> dict[int, list[dict[str, Any]]]:
    # новый ключ (из bot.py)
    if hasattr(runtime, "ALERTS_STORE") and isinstance(getattr(runtime, "ALERTS_STORE"), dict):
        store = runtime.ALERTS_STORE
    else:
        store = getattr(runtime, "ALERTS", None)
        if not isinstance(store, dict):
            runtime.ALERTS = {}
            store = runtime.ALERTS

    # нормализуем
    if not isinstance(store, dict):
        store = {}
    return store


def _user_alerts(user_id: int) -> list[dict[str, Any]]:
    store = _alerts_store()
    if user_id not in store or not isinstance(store[user_id], list):
        store[user_id] = []
    return store[user_id]


# ---------------------------
# дедупликация отправок
# runtime.ALERTS_SENT = set("ad_id:user_id:alert_id")
# ---------------------------
def _sent_store() -> set[str]:
    if not hasattr(runtime, "ALERTS_SENT") or not isinstance(getattr(runtime, "ALERTS_SENT"), set):
        runtime.ALERTS_SENT = set()
    return runtime.ALERTS_SENT


def _sent_key(ad_id: Any, user_id: int, alert_id: str) -> str:
    return f"{ad_id}:{user_id}:{alert_id}"


# ---------------------------
# UI
# ---------------------------
CB_OPEN = "alerts_open"
CB_ADD = "alerts_add"
CB_LIST = "alerts_list"

CB_TARGET_SEEK = "alerts_target:seek"  # ловим Соискателей (резюме)
CB_TARGET_EMP = "alerts_target:emp"    # ловим Работодателей (вакансии)

CB_LOC_SKIP = "alerts_loc:skip"


def _alerts_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить алерт", callback_data=CB_ADD)],
            [InlineKeyboardButton(text="📋 Мои алерты", callback_data=CB_LIST)],
        ]
    )


def _target_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Ловить резюме (Соискатель)", callback_data=CB_TARGET_SEEK)],
            [InlineKeyboardButton(text="🏢 Ловить вакансии (Работодатель)", callback_data=CB_TARGET_EMP)],
        ]
    )


def _skip_location_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить локацию", callback_data=CB_LOC_SKIP)],
        ]
    )


def _open_ad_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Открыть объявление", url=url)]
        ]
    )


# ---------------------------
# SAFE ANSWER
# ---------------------------
async def _safe_answer(cb: CallbackQuery, text: str | None = None, alert: bool = False):
    try:
        if text is None:
            await cb.answer()
        else:
            await cb.answer(text, show_alert=alert)
    except Exception:
        pass


# ---------------------------
# helpers: extract fields from ORM/dict
# ---------------------------
def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_text(s: str) -> str:
    return (s or "").strip().lower()


def _split_keywords(keywords: Iterable[str]) -> list[str]:
    out = []
    for k in keywords or []:
        kk = _normalize_text(str(k))
        if len(kk) >= 2:
            out.append(kk)
    return out


def _ad_target(ad: Any) -> Optional[str]:
    """
    Приводим роль объявления к target алерта:
    - role="employer" -> это вакансия -> target="emp"
    - role="seeker"   -> это резюме   -> target="seek"
    """
    role = _normalize_text(str(_get(ad, "role", "")))
    if role in ("employer", "emp", "vacancy"):
        return "emp"
    if role in ("seeker", "seek", "resume"):
        return "seek"
    return None


def _ad_search_text(ad: Any) -> str:
    # используем get_ad_text если есть (но импортим безопасно, чтобы не словить цикл)
    try:
        from findex_bot.utils.vacancy_utils import get_ad_text  # локальный импорт
        return _normalize_text(get_ad_text(ad))
    except Exception:
        # fallback: title + text + preview_text
        title = _normalize_text(str(_get(ad, "title", "")))
        text = _normalize_text(str(_get(ad, "text", "")))
        preview = _normalize_text(str(_get(ad, "preview_text", "")))
        return " ".join(x for x in [title, text, preview] if x).strip()


def _ad_location(ad: Any) -> str:
    # если у тебя локация хранится иначе — всё равно не упадём
    loc = _get(ad, "location", None)
    if loc is None:
        loc = _get(ad, "city", None)
    if loc is None:
        loc = _get(ad, "geo", None)
    return _normalize_text(str(loc or ""))


def _matches_alert(alert: dict[str, Any], ad: Any) -> bool:
    # target must match
    tgt = alert.get("target")
    ad_tgt = _ad_target(ad)
    if ad_tgt is None or tgt != ad_tgt:
        return False

    # keywords match (OR по ключевым словам)
    kws = _split_keywords(alert.get("keywords") or [])
    if not kws:
        return False

    hay = _ad_search_text(ad)
    if not hay:
        return False

    if not any(k in hay for k in kws):
        return False

    # optional location
    loc_filter = _normalize_text(str(alert.get("location") or ""))
    if loc_filter:
        ad_loc = _ad_location(ad)
        if not ad_loc:
            return False
        if loc_filter not in ad_loc:
            return False

    return True


# ---------------------------
# entry points
# ---------------------------
@router.message(Command("alerts"))
async def alerts_cmd(message: Message):
    await message.answer(
        "🔔 <b>Уведомления / Алерты</b>\n\n"
        "Здесь ты настраиваешь уведомления на нужные объявления.\n"
        "MVP: <b>по должности</b> и (опционально) <b>по локации</b>.",
        reply_markup=_alerts_home_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_OPEN)
async def alerts_open(callback: CallbackQuery):
    await _safe_answer(callback)
    await callback.message.answer(
        "🔔 <b>Уведомления / Алерты</b>\n\n"
        "MVP: <b>по должности</b> и (опционально) <b>по локации</b>.",
        reply_markup=_alerts_home_kb(),
        parse_mode="HTML",
    )


# ---------------------------
# add flow
# ---------------------------
@router.callback_query(F.data == CB_ADD)
async def alerts_add(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)

    await state.clear()
    await state.set_state(AlertFSM.target)

    await callback.message.answer(
        "Кого ловим уведомлением?\n\n"
        "Выбери тип объявлений:",
        reply_markup=_target_kb(),
    )


@router.callback_query(F.data.startswith("alerts_target:"))
async def alerts_pick_target(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)

    target = (callback.data or "").split(":", 1)[-1].strip()
    if target not in ("seek", "emp"):
        await _safe_answer(callback, "⚠️ Неверный выбор", alert=True)
        return

    await state.update_data(target=target)
    await state.set_state(AlertFSM.position)

    what = "резюме (Соискатель)" if target == "seek" else "вакансии (Работодатель)"
    await callback.message.answer(
        f"Ок. Будем ловить: <b>{what}</b>\n\n"
        "Теперь введи ключевые слова по <b>должности</b>.\n"
        "Пример: <code>бармен, бариста, официант</code>\n\n"
        "Можно одно слово или через запятую.",
        parse_mode="HTML",
    )


@router.message(AlertFSM.position)
async def alerts_set_position(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("⚠️ Введи хотя бы одно слово.")
        return

    keywords = [x.strip().lower() for x in raw.replace(";", ",").split(",") if x.strip()]
    keywords = [k for k in keywords if len(k) >= 2]
    if not keywords:
        await message.answer("⚠️ Не вижу ключевых слов. Пример: бармен, бариста")
        return

    await state.update_data(keywords=keywords)
    await state.set_state(AlertFSM.location)

    await message.answer(
        "Отлично.\n\n"
        "Теперь (опционально) введи <b>локацию</b>.\n"
        "Пример: <code>Москва</code> или <code>Химки</code>\n\n"
        "Или нажми «Пропустить локацию».",
        parse_mode="HTML",
        reply_markup=_skip_location_kb(),
    )


@router.callback_query(F.data == CB_LOC_SKIP)
async def alerts_skip_location(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)

    st = await state.get_data()
    user_id = int(callback.from_user.id)

    target = st.get("target")
    keywords = st.get("keywords") or []

    if target not in ("seek", "emp") or not keywords:
        await _safe_answer(callback, "⚠️ Состояние сбилось. Нажми ещё раз «Добавить алерт».", alert=True)
        await state.clear()
        return

    alert_id = uuid.uuid4().hex[:10]
    _user_alerts(user_id).append({
        "id": alert_id,
        "target": target,
        "keywords": list(keywords),
        "location": None,
    })

    await state.clear()
    await callback.message.answer(
        "✅ Алерт добавлен!\n\n"
        "Должности: " + ", ".join(keywords) + "\n"
        "Локация: (любая)",
        reply_markup=_alerts_home_kb(),
    )


@router.message(AlertFSM.location)
async def alerts_set_location(message: Message, state: FSMContext):
    loc = (message.text or "").strip()
    if not loc:
        await message.answer("⚠️ Введи локацию текстом или нажми «Пропустить локацию».")
        return

    st = await state.get_data()
    user_id = int(message.from_user.id)

    target = st.get("target")
    keywords = st.get("keywords") or []

    if target not in ("seek", "emp") or not keywords:
        await message.answer("⚠️ Состояние сбилось. Нажми ещё раз «Добавить алерт».")
        await state.clear()
        return

    alert_id = uuid.uuid4().hex[:10]
    _user_alerts(user_id).append({
        "id": alert_id,
        "target": target,
        "keywords": list(keywords),
        "location": loc.strip().lower(),
    })

    await state.clear()
    await message.answer(
        "✅ Алерт добавлен!\n\n"
        "Должности: " + ", ".join(keywords) + "\n"
        f"Локация: {loc}",
        reply_markup=_alerts_home_kb(),
    )


# ---------------------------
# list / delete
# ---------------------------
def _alerts_list_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for a in _user_alerts(user_id):
        rows.append([
            InlineKeyboardButton(
                text=f"🗑 Удалить #{a['id']}",
                callback_data=f"alerts_del:{a['id']}",
            )
        ])
    if not rows:
        rows = [[InlineKeyboardButton(text="➕ Добавить алерт", callback_data=CB_ADD)]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_alert(a: dict[str, Any]) -> str:
    tgt = "резюме (Соискатель)" if a.get("target") == "seek" else "вакансии (Работодатель)"
    kws = ", ".join(a.get("keywords") or [])
    loc = a.get("location")
    loc_txt = loc if loc else "любая"
    return (
        f"• <b>#{a.get('id')}</b> — ловить <b>{tgt}</b>\n"
        f"  должность: <code>{kws}</code>\n"
        f"  локация: <code>{loc_txt}</code>"
    )


@router.callback_query(F.data == CB_LIST)
async def alerts_list(callback: CallbackQuery):
    await _safe_answer(callback)

    user_id = int(callback.from_user.id)
    items = _user_alerts(user_id)

    if not items:
        await callback.message.answer(
            "📋 <b>Мои алерты</b>\n\nПока пусто. Нажми «Добавить алерт».",
            parse_mode="HTML",
            reply_markup=_alerts_home_kb(),
        )
        return

    text = "📋 <b>Мои алерты</b>\n\n" + "\n\n".join(_format_alert(a) for a in items)
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=_alerts_list_kb(user_id),
    )


@router.callback_query(F.data.startswith("alerts_del:"))
async def alerts_delete(callback: CallbackQuery):
    await _safe_answer(callback)

    user_id = int(callback.from_user.id)
    alert_id = (callback.data or "").split(":", 1)[-1].strip()

    items = _user_alerts(user_id)
    before = len(items)
    items[:] = [a for a in items if str(a.get("id")) != alert_id]
    after = len(items)

    if after == before:
        await _safe_answer(callback, "⚠️ Не найдено", alert=True)
        return

    await callback.message.answer(
        "🗑 Удалено. Хочешь добавить новый или посмотреть список?",
        reply_markup=_alerts_home_kb()
    )


# ============================================================
# PUBLIC API: called from forms.py after publish/approve
# ============================================================
async def fire_alerts_on_publish(bot, ad: Any, url: str | None = None):
    """
    Внешняя точка входа (имя ожидает forms.py).

    ad может быть:
    - ORM объект (findex_bot.db.models.Ad)
    - dict (старый runtime формат)

    url (опционально): ссылка на пост t.me/... — если есть, добавим кнопку "Открыть".
    """
    await _fire_alerts_on_publish(bot, ad, url or "")


async def _fire_alerts_on_publish(bot, ad: Any, url: str = ""):
    """
    Реальная логика алертов.
    """
    try:
        ad_id = _get(ad, "id", None)
        tgt = _ad_target(ad)
        if tgt is None:
            return

        # собираем всех пользователей и их алерты
        store = _alerts_store()
        if not store:
            return

        for user_id, alerts in list(store.items()):
            if not isinstance(alerts, list) or not alerts:
                continue

            for a in alerts:
                try:
                    alert_id = str(a.get("id") or "")
                    if not alert_id:
                        continue

                    # дедуп: один publish -> один алерт на юзера
                    key = _sent_key(ad_id, int(user_id), alert_id)
                    sent = _sent_store()
                    if key in sent:
                        continue

                    if not _matches_alert(a, ad):
                        continue

                    # текст уведомления
                    kind = "резюме" if tgt == "seek" else "вакансия"
                    msg_text = (
                        "🔔 <b>Сработал алерт!</b>\n\n"
                        f"Найдено: <b>{kind}</b>\n"
                    )

                    # добавим коротко условия алерта
                    kws = ", ".join(a.get("keywords") or [])
                    loc = a.get("location") or "любая"
                    msg_text += (
                        f"Должность: <code>{kws}</code>\n"
                        f"Локация: <code>{loc}</code>\n"
                    )

                    # добавим превью объявления
                    preview = _ad_search_text(ad)
                    if preview:
                        # не раздуваем сообщение
                        if len(preview) > 900:
                            preview = preview[:900].rstrip() + "…"
                        msg_text += "\n" + preview

                    # отправка
                    if url:
                        await bot.send_message(int(user_id), msg_text, parse_mode="HTML", reply_markup=_open_ad_kb(url))
                    else:
                        await bot.send_message(int(user_id), msg_text, parse_mode="HTML")

                    sent.add(key)

                except Exception:
                    logger.exception("alerts: failed to process one alert item")

    except Exception:
        logger.exception("alerts: _fire_alerts_on_publish failed")
