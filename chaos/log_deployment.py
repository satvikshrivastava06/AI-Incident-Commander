"""
Log Deployment — Chaos/Tooling Script
-----------------------------------------
Writes a single deployment event (service, version, timestamp)
directly into incident-engine's "deployments" table.

In a real system, this exact write would happen automatically as the
last step of a CI/CD pipeline: "deployment finished, record what just
shipped." Here, you run it manually to simulate that moment whenever
you "redeploy" a service during development.

This connects DIRECTLY to Postgres via asyncpg, rather than going
through incident-engine's HTTP API -- because there is no deployment
API yet, only /incidents exists. That's deliberate: the point right
now is to start accumulating deployment HISTORY in the same table the
root-cause engine will eventually query, well before any API or UI
exists to manage it. The data matters more than the interface to it,
at this stage.

Usage:
    python log_deployment.py --service payment-service --version v1.4.2
    python log_deployment.py --service gateway --version 8f3a9c1
"""

import argparse
import asyncio
import os
import uuid
from datetime import datetime, timezone

import asyncpg
from dotenv import load_dotenv

# Loads variables from a local .env file (gitignored) if one exists --
# a no-op if it doesn't. See .env.example for what's required.
load_dotenv()


def require_env(name: str) -> str:
    """
    Same idea as os.getenv(), but with NO insecure fallback default.
    A hardcoded fallback like os.getenv("POSTGRES_PASSWORD",
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
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "incident_admin")
POSTGRES_PASSWORD = require_env("POSTGRES_PASSWORD")  # CHANGED: was os.getenv with hardcoded default
POSTGRES_DB = os.getenv("POSTGRES_DB", "incident_commander")

TARGET_SERVICES = [
    "inventory-service",
    "auth-service",
    "payment-service",
    "recommendation-service",
    "notification-service",
    "gateway",
]


async def ensure_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS deployments (
            id UUID PRIMARY KEY,
            service_name VARCHAR(100) NOT NULL,
            version VARCHAR(100) NOT NULL,
            deployed_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


async def log_deployment(service: str, version: str) -> uuid.UUID:
    conn = await asyncpg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB,
    )
    try:
        await ensure_table(conn)

        deployment_id = uuid.uuid4()
        deployed_at = datetime.now(timezone.utc)

        await conn.execute(
            """
            INSERT INTO deployments (id, service_name, version, deployed_at)
            VALUES ($1, $2, $3, $4)
            """,
            deployment_id, service, version, deployed_at,
        )
        return deployment_id
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Log a fake deployment event.")
    parser.add_argument("--service", required=True, choices=TARGET_SERVICES, help="Which service was deployed")
    parser.add_argument("--version", required=True, help="Version identifier (git SHA, semver, anything)")
    args = parser.parse_args()

    deployment_id = asyncio.run(log_deployment(args.service, args.version))
    print(f"Logged deployment: service={args.service} version={args.version} id={deployment_id}")


if __name__ == "__main__":
    main()