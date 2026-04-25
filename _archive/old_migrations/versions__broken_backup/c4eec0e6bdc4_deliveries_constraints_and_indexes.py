"""deliveries constraints and indexes

Revision ID: c4eec0e6bdc4
Revises: 3e7c3e916c80
Create Date: 2026-01-26

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4eec0e6bdc4"
down_revision: Union[str, Sequence[str], None] = "3e7c3e916c80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- привести ad_id к bigint (на всякий случай, безопасно) ---
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='deliveries'
                  AND column_name='ad_id'
                  AND data_type <> 'bigint'
            ) THEN
                ALTER TABLE public.deliveries
                    ALTER COLUMN ad_id TYPE bigint USING ad_id::bigint;
            END IF;
        END $$;
        """
    )

    # --- UNIQUE (ad_id, user_tg_id) ---
    # ВАЖНО: у тебя в БД уже есть uq_delivery_ad_user. Не плодим второй уникальный констрейнт.
    op.execute(
        """
        DO $$
        BEGIN
            -- если уже есть правильный uq_delivery_ad_user, то ничего не делаем
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_delivery_ad_user') THEN
                NULL;
            -- иначе создаём (но только если ещё нет нашего альтернативного имени)
            ELSIF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_deliveries_ad_user') THEN
                ALTER TABLE public.deliveries
                ADD CONSTRAINT uq_delivery_ad_user
                UNIQUE (ad_id, user_tg_id);
            END IF;
        END $$;
        """
    )

    # --- Индексы ---
    # У тебя уже есть ix_deliveries_ad и ix_deliveries_ad_id (дубликат). Здесь мы гарантируем наличие "нормальных"
    # и не ломаем текущее состояние.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname='ix_deliveries_ad_id') THEN
                CREATE INDEX ix_deliveries_ad_id ON public.deliveries (ad_id);
            END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname='ix_deliveries_user_tg_id') THEN
                CREATE INDEX ix_deliveries_user_tg_id ON public.deliveries (user_tg_id);
            END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname='ix_deliveries_alert_id') THEN
                CREATE INDEX ix_deliveries_alert_id ON public.deliveries (alert_id);
            END IF;
        END $$;
        """
    )

    # --- FK deliveries.ad_id -> ads.id ---
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='deliveries_ad_id_fkey') THEN
                ALTER TABLE public.deliveries
                ADD CONSTRAINT deliveries_ad_id_fkey
                FOREIGN KEY (ad_id) REFERENCES public.ads(id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )

    # --- FK deliveries.alert_id -> alerts.id ---
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='deliveries_alert_id_fkey') THEN
                ALTER TABLE public.deliveries
                ADD CONSTRAINT deliveries_alert_id_fkey
                FOREIGN KEY (alert_id) REFERENCES public.alerts(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Откат делаем аккуратно: не трогаем то, что могло быть создано не этой миграцией,
    # и поддерживаем оба имени unique-constraint.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='deliveries_alert_id_fkey') THEN
                ALTER TABLE public.deliveries DROP CONSTRAINT deliveries_alert_id_fkey;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='deliveries_ad_id_fkey') THEN
                ALTER TABLE public.deliveries DROP CONSTRAINT deliveries_ad_id_fkey;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_deliveries_ad_user') THEN
                ALTER TABLE public.deliveries DROP CONSTRAINT uq_deliveries_ad_user;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_delivery_ad_user') THEN
                ALTER TABLE public.deliveries DROP CONSTRAINT uq_delivery_ad_user;
            END IF;

            -- индексы удалять не будем (обычно это не обязательно и может снести чужие индексы)
        END $$;
        """
    )
