"""Аналитика/AI: KPI-базлайны, AI-инсайты, бюджетные рекомендации, минус-слова."""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Baseline(Base):
    """Базовые значения показателей за 30 дней (BASE в прототипе).

    Ключи: leads, qual, deals, invoices, payments, revenue, margin, spend,
    first_contact, overdue. Пересчёт по периоду — в сервисе (PMUL).
    """

    __tablename__ = "baselines"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[float] = mapped_column(Float, default=0)


class KpiCard(Base):
    """Карточка KPI дашборда (renderKpis).

    kind: money | count | minutes | percent.
    scales — умножать ли base_value на множитель периода (PMUL).
    static_value — готовая строка для нескалируемых карточек (например ROMI).
    """

    __tablename__ = "kpi_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    key: Mapped[str] = mapped_column(String(48), unique=True)
    label: Mapped[str] = mapped_column(String(96))
    icon: Mapped[str] = mapped_column(String(16), default="")
    svg: Mapped[str] = mapped_column(String, default="")
    kind: Mapped[str] = mapped_column(String(16), default="count")
    base_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scales: Mapped[bool] = mapped_column(Boolean, default=True)
    static_value: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trend: Mapped[str] = mapped_column(String(8), default="up")  # up | down | warn
    delta: Mapped[str] = mapped_column(String(32), default="")
    spark: Mapped[list] = mapped_column(JSON, default=list)
    drill: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AiInsight(Base):
    """AI-инсайт (INSIGHTS)."""

    __tablename__ = "ai_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    sev_label: Mapped[str] = mapped_column(String(48))
    sev_class: Mapped[str] = mapped_column(String(32))
    ic: Mapped[str] = mapped_column(String(24), default="")
    icon: Mapped[str] = mapped_column(String(24), default="")
    title: Mapped[str] = mapped_column(String(255))
    time: Mapped[str] = mapped_column(String(48), default="")
    surface: Mapped[str] = mapped_column(String, default="")
    text: Mapped[str] = mapped_column(String, default="")
    rec: Mapped[str] = mapped_column(String, default="")
    src: Mapped[list] = mapped_column(JSON, default=list)
    conf: Mapped[str] = mapped_column(String(24), default="")
    dep: Mapped[bool] = mapped_column(Boolean, default=False)


class BudgetRec(Base):
    """Рекомендация AI по бюджету (BUDGET_RECS)."""

    __tablename__ = "budget_recs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    ic: Mapped[str] = mapped_column(String(24), default="")
    svg: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String(255))
    tag_label: Mapped[str] = mapped_column(String(64), default="")
    tag_class: Mapped[str] = mapped_column(String(32), default="")
    text: Mapped[str] = mapped_column(String, default="")
    why: Mapped[str] = mapped_column(String, default="")
    impact: Mapped[str] = mapped_column(String(128), default="")
    src: Mapped[list] = mapped_column(JSON, default=list)
    conf: Mapped[str] = mapped_column(String(24), default="")
    dep: Mapped[bool] = mapped_column(Boolean, default=False)


class MinusWord(Base):
    """Кандидат в минус-слова (MW_DATA)."""

    __tablename__ = "minus_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    phrase: Mapped[str] = mapped_column(Text)
    camp: Mapped[str] = mapped_column(String(128), default="")
    level: Mapped[str] = mapped_column(String(48), default="")
    shows: Mapped[int] = mapped_column(BigInteger, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[int] = mapped_column(BigInteger, default=0)
    conv: Mapped[int] = mapped_column(Integer, default=0)
    deals: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(96), default="")
    conf: Mapped[str] = mapped_column(String(24), default="")
    status: Mapped[str] = mapped_column(String(16), default="new")
