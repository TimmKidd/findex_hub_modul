from __future__ import annotations

from aiogram.fsm.context import FSMContext

from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import AdRepo
from findex_bot.utils.moscow_metro import build_moscow_location


async def finalize_location_payload(
    *,
    state: FSMContext,
    station,
):
    if not station:
        return None, None

    location_value = build_moscow_location(station)

    data = await state.get_data()
    ad_id = data.get("ad_id")

    if not ad_id:
        return location_value, None

    async with get_sessionmaker()() as session:
        await AdRepo(session).patch_payload(
            int(ad_id),
            location=location_value,
        )

    return location_value, int(ad_id)
