import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RequestStatus(str, enum.Enum):
    planned = "geplant"
    sent = "angefragt"
    confirmed = "bestätigt"
    deleted = "gelöscht"
    resurfaced = "wieder-aufgetaucht"
    blocked = "blockiert"


class LawBasis(str, enum.Enum):
    gdpr = "DSGVO Art. 17"
    ccpa = "CCPA"
    generic = "Generisch"


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    zip_code: Mapped[str] = mapped_column(String(20), default="")
    country: Mapped[str] = mapped_column(String(2), default="DE")
    phone: Mapped[str] = mapped_column(String(50), default="")
    date_of_birth: Mapped[str] = mapped_column(String(10), default="")
    aliases: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Broker(Base):
    __tablename__ = "brokers"

    id: Mapped[str] = mapped_column(Integer, primary_key=True)
    broker_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), default="")
    website: Mapped[str] = mapped_column(String(255), default="")
    opt_out_url: Mapped[str] = mapped_column(String(512), default="")
    region: Mapped[str] = mapped_column(String(10), default="global")
    category: Mapped[str] = mapped_column(String(50), default="marketing")
    source: Mapped[str] = mapped_column(String(20), default="seed")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TakedownRequest(Base):
    __tablename__ = "takedown_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(Integer, index=True)
    broker_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(
        Enum(RequestStatus), default=RequestStatus.planned, index=True
    )
    law_basis: Mapped[str] = mapped_column(Enum(LawBasis), default=LawBasis.gdpr)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    confirmation_pending: Mapped[bool] = mapped_column(default=False)
    manual_action_url: Mapped[str] = mapped_column(String(512), default="")
    response_note: Mapped[str] = mapped_column(Text, default="")
    request_text: Mapped[str] = mapped_column(Text, default="")
    history: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
