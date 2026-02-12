# 9) findex_bot/db/repo.py

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from findex_bot.db.models import Ad


def _merge_payload(old: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    newp = dict(old or {})
    for k, v in (patch or {}).items():
        newp[k] = v
    return newp


class AdRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, ad_id: int) -> Optional[Ad]:
        res = await self.session.execute(select(Ad).where(Ad.id == ad_id))
        return res.scalar_one_or_none()

    async def get_or_create_draft(self, *, author_user_id: int, role: str) -> Ad:
        res = await self.session.execute(
            select(Ad).where(
                Ad.author_user_id == author_user_id,
                Ad.role == role,
                Ad.status == "draft",
            )
        )
        ad = res.scalar_one_or_none()
        if ad:
            return ad

        ad = Ad(
            author_user_id=author_user_id,
            role=role,
            payload={"role": role},
            status="draft",
            public_url=None,
        )
        self.session.add(ad)
        await self.session.commit()
        await self.session.refresh(ad)
        return ad

    async def patch_payload(self, ad_id: int, **payload_patch) -> None:
        ad = await self.get(ad_id)
        if not ad:
            return
        new_payload = _merge_payload(ad.payload or {}, payload_patch)
        await self.session.execute(
            update(Ad).where(Ad.id == ad_id).values(payload=new_payload)
        )
        await self.session.commit()

    async def set_status(self, ad_id: int, status: str) -> None:
        await self.session.execute(update(Ad).where(Ad.id == ad_id).values(status=status))
        await self.session.commit()

    async def set_public_url(self, ad_id: int, url: str | None) -> None:
        await self.session.execute(update(Ad).where(Ad.id == ad_id).values(public_url=url))
        await self.session.commit()
