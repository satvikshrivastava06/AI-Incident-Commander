"""
Telemetry Consumer
---------------------
Standalone background worker (not a web service) that subscribes to
the "otel-traces" Kafka topic -- the same topic the OTel Collector's
Kafka exporter (Milestone 1.I) fans every trace out to -- and durably
writes a flattened, queryable record of every span into Postgres.

This is intentionally NOT wired into docker-compose yet. Run it
locally against your already-running dockerized Kafka + Postgres
(via their published host ports) while you get comfortable with
consumer groups and offset commits. Containerizing it is a natural
next step once you're happy with how it behaves.

Usage:
    python main.py
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

import asyncpg
from aiokafka import AIOKafkaConsumer
from dotenv import load_dotenv
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

# Loads variables from a local .env file (gitignored) if one exists --
# a no-op if it doesn't. See .env.example for what's required.
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("telemetry-consumer")


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


KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "otel-traces")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "telemetry-consumer-group")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "incident_admin")
POSTGRES_PASSWORD = require_env("POSTGRES_PASSWORD")  # CHANGED: was os.getenv(..., "<default>")
POSTGRES_DB = os.getenv("POSTGRES_DB", "incident_commander")

STATUS_CODE_NAMES = {0: "UNSET", 1: "OK", 2: "ERROR"}


def _hex(raw_bytes: bytes) -> str:
    return raw_bytes.hex()


def _nanos_to_datetime(unix_nanos: int) -> datetime:
    return datetime.fromtimestamp(unix_nanos / 1_000_000_000, tz=timezone.utc)


def parse_trace_batch(raw_value: bytes) -> list[dict]:
    request = ExportTraceServiceRequest()
    request.ParseFromString(raw_value)

    records = []

    for resource_spans in request.resource_spans:
        service_name = "unknown"
        for kv in resource_spans.resource.attributes:
            if kv.key == "service.name":
                service_name = kv.value.string_value

        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                records.append({
                    "trace_id": _hex(span.trace_id),
                    "span_id": _hex(span.span_id),
                    "parent_span_id": _hex(span.parent_span_id) if span.parent_span_id else None,
                    "service_name": service_name,
                    "span_name": span.name,
                    "start_time": _nanos_to_datetime(span.start_time_unix_nano),
                    "end_time": _nanos_to_datetime(span.end_time_unix_nano),
                    "duration_ms": (span.end_time_unix_nano - span.start_time_unix_nano) // 1_000_000,
                    "status_code": STATUS_CODE_NAMES.get(span.status.code, "UNKNOWN"),
                })

    return records


async def create_table_if_missing(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_events (
                span_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                parent_span_id TEXT,
                service_name TEXT NOT NULL,
                span_name TEXT NOT NULL,
                start_time TIMESTAMPTZ NOT NULL,
                end_time TIMESTAMPTZ NOT NULL,
                duration_ms INTEGER NOT NULL,
                status_code TEXT NOT NULL,
                kafka_partition INTEGER NOT NULL,
                kafka_offset BIGINT NOT NULL,
                consumed_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


async def persist_records(pool: asyncpg.Pool, records: list[dict], partition: int, offset: int) -> None:
    if not records:
        return

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO telemetry_events
                (span_id, trace_id, parent_span_id, service_name, span_name,
                 start_time, end_time, duration_ms, status_code,
                 kafka_partition, kafka_offset)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (span_id) DO NOTHING
            """,
            [
                (
                    r["span_id"], r["trace_id"], r["parent_span_id"], r["service_name"],
                    r["span_name"], r["start_time"], r["end_time"], r["duration_ms"],
                    r["status_code"], partition, offset,
                )
                for r in records
            ]
        )


async def main() -> None:
    pool = await asyncpg.create_pool(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB,
        min_size=1,
        max_size=5,
    )
    await create_table_if_missing(pool)

    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=KAFKA_GROUP_ID,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )

    await consumer.start()
    logger.info(
        "Consumer started -> topic=%s group_id=%s bootstrap=%s",
        KAFKA_TOPIC, KAFKA_GROUP_ID, KAFKA_BOOTSTRAP_SERVERS
    )

    total_spans_written = 0

    try:
        async for message in consumer:
            try:
                records = parse_trace_batch(message.value)
                await persist_records(pool, records, message.partition, message.offset)
                total_spans_written += len(records)

                logger.info(
                    "Consumed message -> partition=%s offset=%s spans=%d total_written=%d",
                    message.partition, message.offset, len(records), total_spans_written
                )

                await consumer.commit()

            except Exception:
                logger.exception(
                    "Failed to process message at partition=%s offset=%s -- will be redelivered",
                    message.partition, message.offset
                )

    finally:
        await consumer.stop()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())