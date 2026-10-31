"""
Payment Service
----------------
Fake payment-processing microservice for the synthetic e-commerce system.
"""

import os
import json
import asyncio
import random
import uuid
from datetime import datetime

import asyncpg
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

from prometheus_fastapi_instrumentator import Instrumentator

SERVICE_NAME = "payment-service"
DEPLOYMENT_ID = os.getenv("DEPLOYMENT_ID", "local")
resource = Resource.create({"service.name": SERVICE_NAME, "deployment.id": DEPLOYMENT_ID})

OTEL_COLLECTOR_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
OTEL_AUTH_TOKEN = os.getenv("OTEL_AUTH_TOKEN", "")

tracer_provider = TracerProvider(resource=resource)
_exporter_kwargs = {"endpoint": OTEL_COLLECTOR_ENDPOINT, "insecure": True}
if OTEL_AUTH_TOKEN:
    _exporter_kwargs["headers"] = {"authorization": f"Bearer {OTEL_AUTH_TOKEN}"}
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(**_exporter_kwargs))
)
trace.set_tracer_provider(tracer_provider)

app = FastAPI(
    title="Payment Service",
    description="Mock payment-processing microservice for the AI Incident Commander synthetic e-commerce system.",
    version="0.6.0"
)

FastAPIInstrumentor.instrument_app(app)
AsyncPGInstrumentor().instrument()
RedisInstrumentor().instrument()
Instrumentator().instrument(app).expose(app)


def require_env(name: str) -> str:
    """
    No insecure fallback default -- see backend/incident-engine's
    version of this same helper for the full reasoning. In Kubernetes
    this value is always injected from incident-commander-secrets
    (see the Helm chart's secretEnv wiring), so this only ever raises
    if the Secret itself is misconfigured -- which is exactly when you
    want a loud failure, not a silent connection to a wrong database.
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set.")
    return value


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "incident_admin")
POSTGRES_PASSWORD = require_env("POSTGRES_PASSWORD")  # CHANGED: was os.getenv(..., "<default>")
POSTGRES_DB = os.getenv("POSTGRES_DB", "incident_commander")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

CACHE_TTL_SECONDS = 300

db_pool: asyncpg.Pool | None = None
redis_client: redis.Redis | None = None


class ChargeRequest(BaseModel):
    user_id: str = Field(..., description="The user being charged")
    amount: float = Field(..., gt=0, description="Amount to charge, must be greater than zero")
    currency: str = Field(default="USD", min_length=3, max_length=3)


class ChargeResponse(BaseModel):
    transaction_id: str
    status: str
    amount: float
    currency: str
    user_id: str
    processed_at: str
    latency_ms: int
    source: str = "live"


@app.on_event("startup")
async def startup():
    global db_pool, redis_client

    db_pool = await asyncpg.create_pool(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB,
        min_size=1,
        max_size=10,
    )

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                amount NUMERIC(10, 2) NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL,
                latency_ms INTEGER NOT NULL,
                processed_at TIMESTAMPTZ NOT NULL
            )
            """
        )

    _redis_kwargs = {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "decode_responses": True,
    }
    if REDIS_PASSWORD:
        _redis_kwargs["password"] = REDIS_PASSWORD
    redis_client = redis.Redis(**_redis_kwargs)


@app.on_event("shutdown")
async def shutdown():
    if db_pool is not None:
        await db_pool.close()
    if redis_client is not None:
        await redis_client.aclose()


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "payment-service",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/charge", response_model=ChargeResponse)
async def charge(request: ChargeRequest):
    if random.random() < 0.10:
        delay_seconds = random.uniform(1.5, 3.0)
    else:
        delay_seconds = random.uniform(0.3, 0.8)

    await asyncio.sleep(delay_seconds)

    transaction_id = str(uuid.uuid4())
    processed_at = datetime.utcnow()
    latency_ms = int(delay_seconds * 1000)

    if random.random() < 0.05:
        status = "declined"
        await _persist_transaction(
            transaction_id, request.user_id, request.amount,
            request.currency, status, latency_ms, processed_at
        )
        raise HTTPException(status_code=402, detail="Payment declined by simulated processor")

    status = "success"
    await _persist_transaction(
        transaction_id, request.user_id, request.amount,
        request.currency, status, latency_ms, processed_at
    )

    return ChargeResponse(
        transaction_id=transaction_id,
        status=status,
        amount=request.amount,
        currency=request.currency,
        user_id=request.user_id,
        processed_at=processed_at.isoformat(),
        latency_ms=latency_ms,
        source="live"
    )


@app.get("/charge/{transaction_id}", response_model=ChargeResponse)
async def get_charge(transaction_id: str):
    cache_key = f"transaction:{transaction_id}"

    cached = await redis_client.get(cache_key)
    if cached is not None:
        data = json.loads(cached)
        data["source"] = "cache"
        return ChargeResponse(**data)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM transactions WHERE transaction_id = $1",
            transaction_id
        )

    if row is None:
        raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found")

    data = {
        "transaction_id": row["transaction_id"],
        "status": row["status"],
        "amount": float(row["amount"]),
        "currency": row["currency"],
        "user_id": row["user_id"],
        "processed_at": row["processed_at"].isoformat(),
        "latency_ms": row["latency_ms"],
    }

    await redis_client.set(cache_key, json.dumps(data), ex=CACHE_TTL_SECONDS)

    data["source"] = "database"
    return ChargeResponse(**data)


async def _persist_transaction(
    transaction_id: str,
    user_id: str,
    amount: float,
    currency: str,
    status: str,
    latency_ms: int,
    processed_at: datetime,
) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO transactions
                (transaction_id, user_id, amount, currency, status, latency_ms, processed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            transaction_id, user_id, amount, currency, status, latency_ms, processed_at
        )

    cache_payload = {
        "transaction_id": transaction_id,
        "status": status,
        "amount": amount,
        "currency": currency,
        "user_id": user_id,
        "processed_at": processed_at.isoformat(),
        "latency_ms": latency_ms,
    }
    await redis_client.set(f"transaction:{transaction_id}", json.dumps(cache_payload), ex=CACHE_TTL_SECONDS)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)