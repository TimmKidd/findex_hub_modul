# findex_bot/services/alerts_service.py
from __future__ import annotations

from typing import Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from findex_bot.db.models import Alert, User
from findex_bot.db.repo import AlertRepository, DeliveryRepository


def _open_ad_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть объявление", url=url)]]
    )


async def fire_alerts_on_publish(
    *,
    bot,
    session: AsyncSession,
    ad_id: int,
    role: str,
    payload: dict,
    url: str,
) -> None:
    """
    ЭТАЛОН: вызываем строго после публикации в канал,
    и логируем доставку + дедупим.
    """
    alerts_repo = AlertRepository(session)
    deliveries_repo = DeliveryRepository(session)

    # 1) берём кандидатов по role/keywords/location
    candidates = await alerts_repo.get_active_alerts_for_role(role)

    if not candidates:
        return

    # 2) готовим текст-уведомление (минимально)
    text = "🔔 Подходящее объявление опубликовано!\n\n" \
           f"Роль: {role}\n" \
           f"Ссылка: {url}"

    kb = _open_ad_kb(url)

    # 3) Для каждого alert'а надо узнать tg_user_id владельца (через users)
    #    и отправить сообщение, но с дедупом по (ad_id, user_tg_id)
    for alert in candidates:
        # получаем tg_user_id
        stmt = select(User.tg_user_id).where(User.id == alert.user_id)
        res = await session.execute(stmt)
        tg_user_id = res.scalar_one_or_none()
        if tg_user_id is None:
            continue

        # 4) дедуп: если уже логировали доставку этому юзеру по этому объявлению — пропускаем
        inserted = await deliveries_repo.create_delivery_once(
            ad_id=ad_id,
            user_tg_id=int(tg_user_id),
            alert_id=alert.id,
            status="sent",   # предварительно "sent", если упадёт — обновим на failed (ниже)
            error=None,
        )
        if not inserted:
            # уже отправляли/логировали
            continue

        # 5) отправляем
        try:
            await bot.send_message(
                chat_id=int(tg_user_id),
                text=text,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        except Exception as e:
            # если отправка упала — пишем отдельной записью нельзя (уникальность),
            # поэтому просто обновлять статус будем позже (в следующем шаге добавим update)
            # пока минимально: создадим вторую запись нельзя, значит делаем UPDATE:
            from sqlalchemy import update
            await session.execute(
                update(Delivery)
                .where(Delivery.ad_id == ad_id, Delivery.user_tg_id == int(tg_user_id))
                .values(status="failed", error=str(e)[:1000])
            )
