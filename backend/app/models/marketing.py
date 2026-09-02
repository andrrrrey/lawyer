"""Маркетинг и деньги: Яндекс Директ/Метрика и фактические поступления 1С."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Channel(Base):
    """Рекламный/трафиковый канал (CHANNELS).

    spend=None → источник расхода не подключён (ROMI не считается);
    spend=0    → бесплатный канал (органика, прямые заходы).
    """

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    color: Mapped[str] = mapped_column(String(16))
    # Денежные поля — BigInteger: реальные расход/выручка/маржа выходят за int32.
    spend: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    leads: Mapped[int] = mapped_column(Integer, default=0)
    deals: Mapped[int] = mapped_column(Integer, default=0)
    payments: Mapped[int] = mapped_column(Integer, default=0)
    revenue: Mapped[int] = mapped_column(BigInteger, default=0)
    margin: Mapped[int] = mapped_column(BigInteger, default=0)

    campaigns: Mapped[list[Campaign]] = relationship(
        back_populates="channel", cascade="all, delete-orphan", order_by="Campaign.position"
    )


class Campaign(Base):
    """Рекламная кампания внутри канала (CHANNELS[].campaigns)."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(128))
    spend: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    leads: Mapped[int] = mapped_column(Integer, default=0)
    deals: Mapped[int] = mapped_column(Integer, default=0)
    payments: Mapped[int] = mapped_column(Integer, default=0)
    revenue: Mapped[int] = mapped_column(BigInteger, default=0)
    margin: Mapped[int] = mapped_column(BigInteger, default=0)

    channel: Mapped[Channel] = relationship(back_populates="campaigns")


class Payment(Base):
    """Факт оплаты (Битрикс24 и/или МойСклад). Наполняется на Этапе D."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[int] = mapped_column(BigInteger, default=0)
    source: Mapped[str] = mapped_column(String(32), default="")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- Сырьё источников для сквозной аналитики (Этап D). Схема заводится сейчас. ---


class AdCost(Base):
    """Расходы/клики/показы Яндекс Директа по кампании и дню (Reports API).

    Строка = кампания × дата; расход хранится в базе без НДС. Посуточная разбивка
    нужна для пересчёта показателей под выбранный период.
    """

    __tablename__ = "ad_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    legal_entity_key: Mapped[str] = mapped_column(String(32), default="")
    account_key: Mapped[str] = mapped_column(String(48), default="")
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    campaign: Mapped[str] = mapped_column(String(128), default="")
    # ID кампании Директа — по нему сделки привязываются к кампании (utm_campaign).
    campaign_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    spend: Mapped[int] = mapped_column(BigInteger, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(BigInteger, default=0)


class Visit(Base):
    """Визиты Яндекс Метрики, сгруппированные по дню и источнику.

    Метрика отдаёт агрегат (дата × источник → число сессий), поэтому строка —
    не один визит, а их количество за день: visits. Разбивка по дате нужна,
    чтобы переключатель периода менял показатель «Визиты».
    """

    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    legal_entity_key: Mapped[str] = mapped_column(String(32), default="")
    account_key: Mapped[str] = mapped_column(String(48), default="")
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="")
    utm: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visits: Mapped[int] = mapped_column(Integer, default=0)
    goal_reached: Mapped[bool] = mapped_column(Boolean, default=False)


class Call(Base):
    """Звонок из Calltouch (атрибуция источника)."""

    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="")
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    deal_id: Mapped[int | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True
    )


class Product(Base):
    """Номенклатура/бренд/себестоимость из МойСклад (для маржи, Этап D)."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cost_price: Mapped[float] = mapped_column(Float, default=0)
    profit: Mapped[float] = mapped_column(Float, default=0)


class OneCReceipt(Base):
    """Банковское/кассовое поступление из 1С:УНФ.

    Сохраняется исходный идентификатор регистратора и результат сопоставления
    с Bitrix24 по полям Код_BTX/Тип_BTX. Несопоставленные и исключённые строки
    остаются в журнале для ручного контроля.
    """

    __tablename__ = "one_c_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_key: Mapped[str] = mapped_column(String(72), unique=True)
    registrar_id: Mapped[str] = mapped_column(String(128), default="")
    registrar_number: Mapped[str] = mapped_column(String(64), default="")
    registrar_type: Mapped[str] = mapped_column(String(64), default="")
    registrar_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    legal_entity_key: Mapped[str] = mapped_column(String(32), default="")
    organization_id: Mapped[str] = mapped_column(String(128), default="")
    organization_name: Mapped[str] = mapped_column(String(255), default="")
    organization_inn: Mapped[str] = mapped_column(String(16), default="")
    counterparty_id: Mapped[str] = mapped_column(String(128), default="")
    counterparty_name: Mapped[str] = mapped_column(String(255), default="")
    counterparty_inn: Mapped[str] = mapped_column(String(16), default="")
    contract_id: Mapped[str] = mapped_column(String(128), default="")
    contract_number: Mapped[str] = mapped_column(String(128), default="")

    article_id: Mapped[str] = mapped_column(String(128), default="")
    article_code: Mapped[str] = mapped_column(String(128), default="")
    article_name: Mapped[str] = mapped_column(String(255), default="")
    operation: Mapped[str] = mapped_column(String(16), default="income")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(8), default="RUB")

    crm_source: Mapped[str] = mapped_column(String(32), default="")
    crm_entity_type: Mapped[str] = mapped_column(String(16), default="")
    crm_external_id: Mapped[str] = mapped_column(String(48), default="")
    matched_deal_id: Mapped[int | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True
    )
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str] = mapped_column(String(255), default="")
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
