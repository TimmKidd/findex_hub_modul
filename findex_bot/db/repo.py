# findex_bot/db/repo.py
from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, update, insert, func, case, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from findex_bot.db.models import (
    Ad,
    Respond,
    RespondEvent,
    RespondDailyLimit,
    CandidateProfile,
)


# ----------------------------
# Helpers
# ----------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _merge_payload(old: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    newp = dict(old or {})
    for k, v in (patch or {}).items():
        newp[k] = v
    return newp


def _clean_payload_for_clone(payload: dict[str, Any]) -> dict[str, Any]:
    """
    При клонировании объявления для повторной публикации:
    - сохраняем контент
    - выкидываем служебные поля
    """
    p = dict(payload or {})

    for k in (
        "moderation_chat_id",
        "moderation_message_id",
        "moderation_album_message_ids",
        "preview_chat_id",
        "preview_message_id",
        "preview_is_media",
        "preview_status",
        "preview_collapsed",
        "preview_album_message_ids",
        "published_album_message_ids",
        "sent_to_moderation",
        "published_at",
        "public_url",
        "rejected_reason",
        "rejected_field",
        "reject_notice_chat_id",
        "reject_notice_message_id",
    ):
        p.pop(k, None)

    return p


def _structured_dict(value: dict | None) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _resurrection_messages(structured: dict | None) -> list[dict[str, Any]]:
    s = _structured_dict(structured)
    msgs = s.get("resurrection_messages")
    if not isinstance(msgs, list):
        return []
    clean: list[dict[str, Any]] = []
    for item in msgs:
        if isinstance(item, dict):
            clean.append(dict(item))
    return clean


# ----------------------------
# Ads
# ----------------------------
class AdRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, ad_id: int) -> Optional[Ad]:
        res = await self.session.execute(select(Ad).where(Ad.id == ad_id))
        return res.scalar_one_or_none()

    async def get_or_create_draft(self, *, author_user_id: int, role: str) -> Ad:
        role = str(role).strip().lower()

        res = await self.session.execute(
            select(Ad)
            .where(
                Ad.author_user_id == author_user_id,
                Ad.role == role,
                Ad.status == "draft",
            )
            .order_by(Ad.updated_at.desc(), Ad.id.desc())
        )

        # БЕРЁМ САМЫЙ СВЕЖИЙ DRAFT, НЕ ПАДАЕМ НА ДУБЛЯХ
        ad = res.scalars().first()
        if ad:
            return ad

        ad = Ad(
            author_user_id=author_user_id,
            role=role,
            payload={"role": role, "ad_role": role},
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

        raw_role = payload_patch.get("role")
        if raw_role is None:
            raw_role = payload_patch.get("ad_role")

        if raw_role is not None:
            role = str(raw_role).strip().lower()
            if role in {"seeker", "employer"}:
                new_payload["role"] = role
                new_payload["ad_role"] = role
                await self.session.execute(
                    update(Ad).where(Ad.id == ad_id).values(payload=new_payload, role=role)
                )
                await self.session.commit()
                return

        await self.session.execute(update(Ad).where(Ad.id == ad_id).values(payload=new_payload))
        await self.session.commit()

    async def set_status(self, ad_id: int, status: str) -> None:
        await self.session.execute(update(Ad).where(Ad.id == ad_id).values(status=status))
        await self.session.commit()

    async def set_public_url(self, ad_id: int, url: str | None) -> None:
        await self.session.execute(update(Ad).where(Ad.id == ad_id).values(public_url=url))
        await self.session.commit()

    async def clone_for_republish(self, *, source_ad_id: int, author_user_id: int) -> Optional[Ad]:
        src = await self.get(source_ad_id)
        if not src:
            return None
        if int(getattr(src, "author_user_id", 0) or 0) != int(author_user_id):
            return None

        new_payload = _clean_payload_for_clone(src.payload or {})
        role = str((new_payload.get("role") or new_payload.get("ad_role") or src.role or "")).strip().lower()
        if role not in {"seeker", "employer"}:
            role = str(getattr(src, "role", "") or "employer").strip().lower()
            if role not in {"seeker", "employer"}:
                role = "employer"

        new_payload["role"] = role
        new_payload["ad_role"] = role

        existing_draft = await self.session.scalar(
            select(Ad).where(
                Ad.author_user_id == int(author_user_id),
                Ad.role == role,
                Ad.status == "draft",
            )
        )

        if existing_draft:
            existing_draft.payload = new_payload
            existing_draft.public_url = None
            existing_draft.status = "draft"
            await self.session.commit()
            await self.session.refresh(existing_draft)
            return existing_draft

        new_ad = Ad(
            author_user_id=src.author_user_id,
            role=role,
            payload=new_payload,
            status="draft",
            public_url=None,
        )
        self.session.add(new_ad)
        await self.session.commit()
        await self.session.refresh(new_ad)
        return new_ad


# ----------------------------
# Candidate profiles
# ----------------------------
class CandidateProfileRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: int) -> Optional[CandidateProfile]:
        res = await self.session.execute(
            select(CandidateProfile).where(CandidateProfile.user_id == int(user_id))
        )
        return res.scalar_one_or_none()

    async def upsert_profile(
        self,
        *,
        user_id: int,
        username: str | None,
        telegram_first_name: str | None,
        telegram_last_name: str | None,
        full_name: str,
        age: int,
        citizenship: str,
        experience: str,
        resume_link: str | None,
        resume_file_id: str | None,
        resume_file_name: str | None,
        last_responded_at: datetime | None = None,
    ) -> CandidateProfile:
        has_resume = bool((resume_link or "").strip() or (resume_file_id or "").strip())

        stmt = (
            pg_insert(CandidateProfile)
            .values(
                user_id=int(user_id),
                username=(username or None),
                telegram_first_name=(telegram_first_name or None),
                telegram_last_name=(telegram_last_name or None),
                full_name=str(full_name).strip(),
                age=int(age),
                citizenship=str(citizenship).strip(),
                experience=str(experience).strip(),
                resume_link=(resume_link or None),
                resume_file_id=(resume_file_id or None),
                resume_file_name=(resume_file_name or None),
                has_resume=bool(has_resume),
                last_responded_at=last_responded_at,
            )
            .on_conflict_do_update(
                index_elements=[CandidateProfile.user_id],
                set_={
                    "username": (username or None),
                    "telegram_first_name": (telegram_first_name or None),
                    "telegram_last_name": (telegram_last_name or None),
                    "full_name": str(full_name).strip(),
                    "age": int(age),
                    "citizenship": str(citizenship).strip(),
                    "experience": str(experience).strip(),
                    "resume_link": (resume_link or None),
                    "resume_file_id": (resume_file_id or None),
                    "resume_file_name": (resume_file_name or None),
                    "has_resume": bool(has_resume),
                    "last_responded_at": last_responded_at,
                    "updated_at": _now_utc(),
                },
            )
        )

        await self.session.execute(stmt)
        await self.session.commit()

        res = await self.session.execute(
            select(CandidateProfile).where(CandidateProfile.user_id == int(user_id))
        )
        return res.scalar_one()

    async def touch_last_responded_at(self, user_id: int, *, dt: datetime | None = None) -> None:
        await self.session.execute(
            update(CandidateProfile)
            .where(CandidateProfile.user_id == int(user_id))
            .values(
                last_responded_at=(dt or _now_utc()),
                updated_at=_now_utc(),
            )
        )
        await self.session.commit()

    async def list_profiles(
        self,
        *,
        citizenship: str | None = None,
        age_from: int | None = None,
        age_to: int | None = None,
        username: str | None = None,
        has_resume: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CandidateProfile]:
        q = select(CandidateProfile)

        if citizenship:
            q = q.where(CandidateProfile.citizenship.ilike(f"%{citizenship.strip()}%"))

        if age_from is not None:
            q = q.where(CandidateProfile.age >= int(age_from))

        if age_to is not None:
            q = q.where(CandidateProfile.age <= int(age_to))

        if username:
            uname = username.strip().lstrip("@")
            q = q.where(CandidateProfile.username.ilike(uname))

        if has_resume is not None:
            q = q.where(CandidateProfile.has_resume == bool(has_resume))

        q = q.order_by(
            func.coalesce(CandidateProfile.last_responded_at, CandidateProfile.updated_at).desc()
        ).limit(limit).offset(offset)

        res = await self.session.execute(q)
        return list(res.scalars().all())

    async def count_profiles(
        self,
        *,
        citizenship: str | None = None,
        age_from: int | None = None,
        age_to: int | None = None,
        username: str | None = None,
        has_resume: bool | None = None,
    ) -> int:
        q = select(func.count()).select_from(CandidateProfile)

        if citizenship:
            q = q.where(CandidateProfile.citizenship.ilike(f"%{citizenship.strip()}%"))

        if age_from is not None:
            q = q.where(CandidateProfile.age >= int(age_from))

        if age_to is not None:
            q = q.where(CandidateProfile.age <= int(age_to))

        if username:
            uname = username.strip().lstrip("@")
            q = q.where(CandidateProfile.username.ilike(uname))

        if has_resume is not None:
            q = q.where(CandidateProfile.has_resume == bool(has_resume))

        res = await self.session.execute(q)
        return int(res.scalar_one() or 0)


# ----------------------------
# Responds
# ----------------------------
class RespondRepo:
    ACTIVE_STATUSES = ("INVITED", "IN_DIALOG", "NEW")
    CLOSED_STATUSES = ("CLOSED_BY_OWNER", "CLOSED_BY_CANDIDATE", "CLOSED_SYSTEM")

    def __init__(self, session: AsyncSession):
        self.session = session

    # -------- infra --------
    async def ensure_dedup_unique_index(self) -> None:
        await self.session.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_respond_events_dedup_key
            ON respond_events (dedup_key)
            WHERE dedup_key IS NOT NULL
        """))
        await self.session.commit()

    # -------- basic getters --------
    async def respond_exists(self, *, ad_id: int, candidate_user_id: int) -> bool:
        res = await self.session.execute(
            select(Respond.id).where(
                Respond.ad_id == ad_id,
                Respond.candidate_user_id == candidate_user_id,
            )
        )
        return res.scalar_one_or_none() is not None

    async def get_by_id(self, respond_id: int) -> Optional[Respond]:
        res = await self.session.execute(select(Respond).where(Respond.id == respond_id))
        return res.scalar_one_or_none()

    async def get_by_ad_and_candidate(self, *, ad_id: int, candidate_user_id: int) -> Optional[Respond]:
        res = await self.session.execute(
            select(Respond).where(
                Respond.ad_id == ad_id,
                Respond.candidate_user_id == candidate_user_id,
            )
        )
        return res.scalar_one_or_none()

    # -------- create --------
    async def create_respond(
        self,
        *,
        ad: Ad,
        candidate_user_id: int,
        mode: str,
        candidate_message: str,
        contacts: dict | None,
        structured: dict | None,
        author_chat_id: int,
        candidate_chat_id: int,
    ) -> Respond:
        respond = Respond(
            ad_id=ad.id,
            author_user_id=ad.author_user_id,
            candidate_user_id=candidate_user_id,
            mode=mode,
            status="NEW",
            candidate_message=candidate_message,
            contacts=contacts,
            structured=structured,
            ad_public_url=ad.public_url,
            ad_role=ad.role,
            ad_payload_snapshot=ad.payload,
            author_chat_id=author_chat_id,
            author_message_id=None,
            candidate_chat_id=candidate_chat_id,
            candidate_message_id=None,
            last_candidate_activity_at=_now_utc(),
        )
        self.session.add(respond)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise
        await self.session.refresh(respond)
        return respond

    # -------- patch structured --------
    async def patch_structured(self, respond_id: int, *, patch: dict[str, Any]) -> Optional[Respond]:
        r = await self.get_by_id(int(respond_id))
        if not r:
            return None

        old = _structured_dict(getattr(r, "structured", None))
        new_structured = dict(old)
        for k, v in (patch or {}).items():
            new_structured[k] = v

        r.structured = new_structured  # type: ignore

        try:
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(r, "structured")
        except Exception:
            pass

        await self.session.commit()
        await self.session.refresh(r)
        return r

    # -------- events --------
    async def add_event(
        self,
        *,
        respond_id: int,
        actor_role: str,
        actor_user_id: int | None,
        event_type: str,
        payload: dict | None = None,
        dedup_key: str | None = None,
    ) -> RespondEvent:
        if dedup_key:
            stmt = (
                pg_insert(RespondEvent)
                .values(
                    respond_id=respond_id,
                    actor_role=actor_role,
                    actor_user_id=actor_user_id,
                    event_type=event_type,
                    payload=payload or {},
                    dedup_key=dedup_key,
                )
                .on_conflict_do_nothing(
                    index_elements=["dedup_key"],
                    index_where=RespondEvent.dedup_key.is_not(None),
                )
                .returning(RespondEvent.id)
            )
            res = await self.session.execute(stmt)
            ev_id = res.scalar_one_or_none()
            await self.session.commit()

            if ev_id is not None:
                res3 = await self.session.execute(select(RespondEvent).where(RespondEvent.id == ev_id))
                ev = res3.scalar_one()
                setattr(ev, "_dedup_inserted", True)
                return ev

            res2 = await self.session.execute(select(RespondEvent).where(RespondEvent.dedup_key == dedup_key))
            ev = res2.scalar_one_or_none()
            if ev is None:
                ev = RespondEvent(
                    respond_id=respond_id,
                    actor_role=actor_role,
                    actor_user_id=actor_user_id,
                    event_type=event_type,
                    payload=payload or {},
                    dedup_key=dedup_key,
                )
                self.session.add(ev)
                await self.session.commit()
                await self.session.refresh(ev)
                setattr(ev, "_dedup_inserted", True)
                return ev

            setattr(ev, "_dedup_inserted", False)
            return ev

        ev = RespondEvent(
            respond_id=respond_id,
            actor_role=actor_role,
            actor_user_id=actor_user_id,
            event_type=event_type,
            payload=payload or {},
            dedup_key=None,
        )
        self.session.add(ev)
        await self.session.commit()
        await self.session.refresh(ev)
        setattr(ev, "_dedup_inserted", True)
        return ev

    async def add_event_once(
        self,
        *,
        respond_id: int,
        actor_role: str,
        actor_user_id: int | None,
        event_type: str,
        payload: dict | None = None,
        dedup_key: str,
    ) -> bool:
        stmt = (
            pg_insert(RespondEvent)
            .values(
                respond_id=respond_id,
                actor_role=actor_role,
                actor_user_id=actor_user_id,
                event_type=event_type,
                payload=payload or {},
                dedup_key=dedup_key,
            )
            .on_conflict_do_nothing(
                index_elements=["dedup_key"],
                index_where=RespondEvent.dedup_key.is_not(None),
            )
            .returning(RespondEvent.id)
        )

        res = await self.session.execute(stmt)
        ev_id = res.scalar_one_or_none()
        await self.session.commit()
        return ev_id is not None

    # -------- status / activity --------
    async def set_status(self, respond_id: int, status: str, *, closed_at: datetime | None = None) -> None:
        values: dict[str, Any] = {"status": status}
        if closed_at is not None:
            values["closed_at"] = closed_at
        await self.session.execute(update(Respond).where(Respond.id == respond_id).values(**values))
        await self.session.commit()

    async def set_invited(self, respond_id: int) -> None:
        await self.session.execute(
            update(Respond).where(Respond.id == respond_id).values(
                status="INVITED",
                invited_at=_now_utc(),
            )
        )
        await self.session.commit()

    async def touch_author_activity(self, respond_id: int) -> None:
        await self.session.execute(
            update(Respond).where(Respond.id == respond_id).values(last_author_activity_at=_now_utc())
        )
        await self.session.commit()

    async def touch_candidate_activity(self, respond_id: int) -> None:
        await self.session.execute(
            update(Respond).where(Respond.id == respond_id).values(last_candidate_activity_at=_now_utc())
        )
        await self.session.commit()

    async def set_author_message_meta(self, respond_id: int, *, chat_id: int, message_id: int) -> None:
        await self.session.execute(
            update(Respond).where(Respond.id == respond_id).values(
                author_chat_id=chat_id,
                author_message_id=message_id,
            )
        )
        await self.session.commit()

    async def set_candidate_message_meta(self, respond_id: int, *, chat_id: int, message_id: int) -> None:
        await self.session.execute(
            update(Respond).where(Respond.id == respond_id).values(
                candidate_chat_id=chat_id,
                candidate_message_id=message_id,
            )
        )
        await self.session.commit()

    # -------- viewed/notified --------
    async def mark_owner_viewed_if_null(self, respond_id: int) -> bool:
        res = await self.session.execute(
            update(Respond)
            .where(Respond.id == respond_id, Respond.owner_viewed_at.is_(None))
            .values(owner_viewed_at=_now_utc())
            .returning(Respond.id)
        )
        await self.session.commit()
        return res.scalar_one_or_none() is not None

    async def mark_owner_notified_if_null(self, respond_id: int) -> bool:
        res = await self.session.execute(
            update(Respond)
            .where(Respond.id == respond_id, Respond.owner_notified_at.is_(None))
            .values(owner_notified_at=_now_utc())
            .returning(Respond.id)
        )
        await self.session.commit()
        return res.scalar_one_or_none() is not None

    async def mark_author_viewed_if_null(self, respond_id: int) -> bool:
        return await self.mark_owner_viewed_if_null(respond_id)

    async def mark_author_notified_if_null(self, respond_id: int) -> bool:
        return await self.mark_owner_notified_if_null(respond_id)

    # -------- ordering helpers --------
    def _active_status_order_expr(self):
        return case(
            (Respond.status == "INVITED", 0),
            (Respond.status == "IN_DIALOG", 1),
            (Respond.status == "NEW", 2),
            else_=99,
        )

    def _closed_status_order_expr(self):
        return case(
            (Respond.status == "CLOSED_BY_OWNER", 0),
            (Respond.status == "CLOSED_BY_CANDIDATE", 1),
            (Respond.status == "CLOSED_SYSTEM", 2),
            else_=99,
        )

    def _activity_dt_expr(self):
        return func.coalesce(
            Respond.closed_at,
            Respond.last_author_activity_at,
            Respond.last_candidate_activity_at,
            Respond.invited_at,
            Respond.created_at,
        )

    # -------- lists / counts --------
    async def list_by_ad(self, *, ad_id: int, flt: str = "all", limit: int = 50, offset: int = 0) -> list[Respond]:
        q = select(Respond).where(Respond.ad_id == ad_id)

        if flt == "unread":
            q = q.where(Respond.status == "NEW", Respond.owner_viewed_at.is_(None))
        elif flt == "dialog":
            q = q.where(Respond.status == "IN_DIALOG")
        elif flt == "invited":
            q = q.where(Respond.status == "INVITED")
        elif flt == "closed":
            q = q.where(Respond.status.in_(["CLOSED_BY_OWNER", "CLOSED_BY_CANDIDATE", "CLOSED_SYSTEM"]))

        q = q.order_by(
            func.coalesce(Respond.last_author_activity_at, Respond.last_candidate_activity_at, Respond.created_at).desc()
        ).limit(limit).offset(offset)

        res = await self.session.execute(q)
        return list(res.scalars().all())

    async def counts_by_ad(self, *, ad_id: int) -> dict[str, int]:
        stmt = select(
            func.count().label("total"),
            func.sum(case((((Respond.status == "NEW") & (Respond.owner_viewed_at.is_(None))), 1), else_=0)).label("unread"),
            func.sum(case(((Respond.status == "IN_DIALOG"), 1), else_=0)).label("dialog"),
            func.sum(case(((Respond.status == "INVITED"), 1), else_=0)).label("invited"),
            func.sum(case(((Respond.status.in_(["CLOSED_BY_OWNER", "CLOSED_BY_CANDIDATE", "CLOSED_SYSTEM"])), 1), else_=0)).label("closed"),
        ).where(Respond.ad_id == ad_id)

        r = (await self.session.execute(stmt)).one()
        return {
            "total": int(r.total or 0),
            "unread": int(r.unread or 0),
            "dialog": int(r.dialog or 0),
            "invited": int(r.invited or 0),
            "closed": int(r.closed or 0),
        }

    async def list_for_user(
        self,
        *,
        user_id: int,
        side: str,
        bucket: str = "all",
        limit: int = 10,
        offset: int = 0,
    ) -> list[Respond]:
        if side == "candidate":
            q = select(Respond).where(Respond.candidate_user_id == int(user_id))
        elif side == "author":
            q = select(Respond).where(Respond.author_user_id == int(user_id))
        else:
            return []

        if bucket == "active":
            q = q.where(Respond.status.in_(self.ACTIVE_STATUSES))
            q = q.order_by(
                self._active_status_order_expr().asc(),
                self._activity_dt_expr().desc(),
            )
        elif bucket == "closed":
            q = q.where(Respond.status.in_(self.CLOSED_STATUSES))
            q = q.order_by(
                self._activity_dt_expr().desc(),
                self._closed_status_order_expr().asc(),
            )
        else:
            q = q.order_by(
                case(
                    (Respond.status.in_(self.ACTIVE_STATUSES), 0),
                    else_=1,
                ).asc(),
                self._active_status_order_expr().asc(),
                self._activity_dt_expr().desc(),
            )

        q = q.limit(limit).offset(offset)

        res = await self.session.execute(q)
        return list(res.scalars().all())

    async def count_for_user(
        self,
        *,
        user_id: int,
        side: str,
        bucket: str = "all",
    ) -> int:
        if side == "candidate":
            stmt = select(func.count()).select_from(Respond).where(Respond.candidate_user_id == int(user_id))
        elif side == "author":
            stmt = select(func.count()).select_from(Respond).where(Respond.author_user_id == int(user_id))
        else:
            return 0

        if bucket == "active":
            stmt = stmt.where(Respond.status.in_(self.ACTIVE_STATUSES))
        elif bucket == "closed":
            stmt = stmt.where(Respond.status.in_(self.CLOSED_STATUSES))

        res = await self.session.execute(stmt)
        return int(res.scalar_one() or 0)

    async def counts_for_user(self, *, user_id: int, side: str) -> dict[str, int]:
        if side == "candidate":
            where_expr = (Respond.candidate_user_id == int(user_id))
        elif side == "author":
            where_expr = (Respond.author_user_id == int(user_id))
        else:
            return {"active": 0, "closed": 0, "total": 0}

        stmt = select(
            func.count().label("total"),
            func.sum(case(((Respond.status.in_(self.ACTIVE_STATUSES), 1)), else_=0)).label("active"),
            func.sum(case(((Respond.status.in_(self.CLOSED_STATUSES), 1)), else_=0)).label("closed"),
        ).where(where_expr)

        r = (await self.session.execute(stmt)).one()
        return {
            "total": int(r.total or 0),
            "active": int(r.active or 0),
            "closed": int(r.closed or 0),
        }

    # -------- jobs advisory lock --------
    async def try_acquire_jobs_lock(self, lock_id: int) -> bool:
        res = await self.session.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": int(lock_id)})
        return bool(res.scalar())

    async def release_jobs_lock(self, lock_id: int) -> None:
        await self.session.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": int(lock_id)})
        await self.session.commit()

    # -------- jobs: pick lists --------
    async def pick_for_ping12(self, *, now_utc: datetime) -> list[Respond]:
        cutoff = now_utc - timedelta(hours=12)
        q = (
            select(Respond)
            .where(
                Respond.status == "INVITED",
                Respond.invited_at.is_not(None),
                Respond.invited_at <= cutoff,
                Respond.ping12_sent_at.is_(None),
                func.coalesce(Respond.last_candidate_activity_at, Respond.invited_at) <= Respond.invited_at,
            )
            .order_by(Respond.invited_at.asc())
            .limit(200)
        )
        res = await self.session.execute(q)
        return list(res.scalars().all())

    async def pick_for_ping36(self, *, now_utc: datetime) -> list[Respond]:
        cutoff = now_utc - timedelta(hours=36)
        q = (
            select(Respond)
            .where(
                Respond.status == "INVITED",
                Respond.invited_at.is_not(None),
                Respond.invited_at <= cutoff,
                Respond.ping36_sent_at.is_(None),
                func.coalesce(Respond.last_candidate_activity_at, Respond.invited_at) <= Respond.invited_at,
            )
            .order_by(Respond.invited_at.asc())
            .limit(200)
        )
        res = await self.session.execute(q)
        return list(res.scalars().all())

    async def pick_for_owner24(self, *, now_utc: datetime) -> list[Respond]:
        cutoff = now_utc - timedelta(hours=24)
        q = (
            select(Respond)
            .where(
                Respond.status.in_(["NEW", "INVITED", "IN_DIALOG"]),
                Respond.last_candidate_activity_at.is_not(None),
                Respond.last_candidate_activity_at <= cutoff,
                Respond.ping_owner24_sent_at.is_(None),
                func.coalesce(Respond.last_author_activity_at, datetime(1970, 1, 1)) <= Respond.last_candidate_activity_at,
            )
            .order_by(Respond.last_candidate_activity_at.asc())
            .limit(200)
        )
        res = await self.session.execute(q)
        return list(res.scalars().all())

    # -------- jobs: reserve flags --------
    async def reserve_ping12(self, respond_id: int) -> bool:
        res = await self.session.execute(
            update(Respond)
            .where(Respond.id == respond_id, Respond.ping12_sent_at.is_(None))
            .values(ping12_sent_at=_now_utc())
            .returning(Respond.id)
        )
        await self.session.commit()
        return res.scalar_one_or_none() is not None

    async def reserve_ping36(self, respond_id: int) -> bool:
        res = await self.session.execute(
            update(Respond)
            .where(Respond.id == respond_id, Respond.ping36_sent_at.is_(None))
            .values(ping36_sent_at=_now_utc())
            .returning(Respond.id)
        )
        await self.session.commit()
        return res.scalar_one_or_none() is not None

    async def reserve_ping_owner24(self, respond_id: int) -> bool:
        res = await self.session.execute(
            update(Respond)
            .where(Respond.id == respond_id, Respond.ping_owner24_sent_at.is_(None))
            .values(ping_owner24_sent_at=_now_utc())
            .returning(Respond.id)
        )
        await self.session.commit()
        return res.scalar_one_or_none() is not None

    # -------- resurrection storage: unified format --------
    async def append_resurrection_message(
        self,
        *,
        respond_id: int,
        chat_id: int,
        message_id: int,
        side: str,
        stage: str,
        scenario: str,
    ) -> None:
        r = await self.get_by_id(respond_id)
        if not r:
            return

        structured = _structured_dict(getattr(r, "structured", None))
        msgs = _resurrection_messages(structured)

        msgs.append({
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "side": str(side),
            "stage": str(stage),
            "scenario": str(scenario),
        })

        structured["resurrection_messages"] = msgs
        r.structured = structured  # type: ignore

        try:
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(r, "structured")
        except Exception:
            pass

        await self.session.commit()

    async def list_resurrection_messages(
        self,
        *,
        respond_id: int,
        side: str | None = None,
        scenario: str | None = None,
    ) -> list[dict[str, Any]]:
        r = await self.get_by_id(respond_id)
        if not r:
            return []

        msgs = _resurrection_messages(getattr(r, "structured", None))
        out: list[dict[str, Any]] = []

        for item in msgs:
            if side is not None and str(item.get("side") or "") != str(side):
                continue
            if scenario is not None and str(item.get("scenario") or "") != str(scenario):
                continue
            out.append(dict(item))

        return out

    async def clear_resurrection_messages(
        self,
        *,
        respond_id: int,
        side: str | None = None,
        scenario: str | None = None,
    ) -> list[dict[str, Any]]:
        r = await self.get_by_id(respond_id)
        if not r:
            return []

        structured = _structured_dict(getattr(r, "structured", None))
        msgs = _resurrection_messages(structured)

        removed: list[dict[str, Any]] = []
        kept: list[dict[str, Any]] = []

        for item in msgs:
            item_side = str(item.get("side") or "")
            item_scenario = str(item.get("scenario") or "")

            match_side = side is None or item_side == str(side)
            match_scenario = scenario is None or item_scenario == str(scenario)

            if match_side and match_scenario:
                removed.append(dict(item))
            else:
                kept.append(dict(item))

        structured["resurrection_messages"] = kept
        r.structured = structured  # type: ignore

        try:
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(r, "structured")
        except Exception:
            pass

        await self.session.commit()
        return removed

    async def replace_resurrection_messages(
        self,
        *,
        respond_id: int,
        side: str,
        scenario: str,
        new_items: list[dict[str, Any]],
    ) -> None:
        r = await self.get_by_id(respond_id)
        if not r:
            return

        structured = _structured_dict(getattr(r, "structured", None))
        msgs = _resurrection_messages(structured)

        kept: list[dict[str, Any]] = []
        for item in msgs:
            if str(item.get("side") or "") == str(side) and str(item.get("scenario") or "") == str(scenario):
                continue
            kept.append(dict(item))

        for item in new_items:
            if not isinstance(item, dict):
                continue
            kept.append(dict(item))

        structured["resurrection_messages"] = kept
        r.structured = structured  # type: ignore

        try:
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(r, "structured")
        except Exception:
            pass

        await self.session.commit()

    # -------- daily limits --------
    async def inc_daily_limit(self, *, user_id: int, day: date) -> int:
        stmt = (
            insert(RespondDailyLimit)
            .values(
                user_id=user_id,
                day=day,
                count=1,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "day"],
                set_={"count": RespondDailyLimit.count + 1, "updated_at": _now_utc()},
            )
            .returning(RespondDailyLimit.count)
        )

        res = await self.session.execute(stmt)
        await self.session.commit()
        return int(res.scalar_one())

    async def get_daily_limit(self, *, user_id: int, day: date) -> int:
        res = await self.session.execute(
            select(RespondDailyLimit.count).where(
                RespondDailyLimit.user_id == user_id,
                RespondDailyLimit.day == day,
            )
        )
        v = res.scalar_one_or_none()
        return int(v or 0)