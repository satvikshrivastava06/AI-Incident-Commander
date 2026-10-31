"""
Incident Engine — Database Models
------------------------------------
SQLAlchemy ORM models for the Incident Engine.
"""

import os
import uuid
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import Boolean, ForeignKey, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Loads variables from a local .env file (gitignored) if one exists --
# a no-op if it doesn't. See .env.example for what's required. This is
# what lets this standalone process (run directly with `python
# main.py`, not deployed via the Helm chart) get its Postgres
# password without ever hardcoding one in source.
load_dotenv()


def require_env(name: str) -> str:
    """
    Same idea as os.getenv(), but with NO insecure fallback default.
    A hardcoded fallback like os.getenv("POSTGRES_PASSWORD",
    "<default>") means a real-looking password sits in git
    forever, and the app "works" even when nobody configured it --
    silently connecting with a guessable, publicly-visible credential.
    Failing loudly here instead makes a missing secret impossible to miss.
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env in this directory and fill in a real value."
        )
    return value


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "incident_admin")
POSTGRES_PASSWORD = require_env("POSTGRES_PASSWORD")
POSTGRES_DB = os.getenv("POSTGRES_DB", "incident_commander")

DATABASE_URL = (
    f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    incidents: Mapped[list["Incident"]] = relationship(back_populates="related_deployment")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    related_deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=True
    )
    related_deployment: Mapped["Deployment | None"] = relationship(back_populates="incidents")
    confirmed_root_cause: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RootCausePrediction(Base):
    __tablename__ = "root_cause_predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    ranked_causes_json: Mapped[str] = mapped_column(Text, nullable=False)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)