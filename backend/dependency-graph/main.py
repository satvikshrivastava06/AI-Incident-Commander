"""
Dependency Graph Service
---------------------------
Exposes the live dependency graph over a simple HTTP API.

Exposes:
  - GET /health  -> liveness check (UNAUTHENTICATED)
  - GET /graph   -> current nodes + edges as JSON (requires X-API-Key)
"""

import asyncio
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from builder import DependencyGraphBuilder, run_consumer

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dependency-graph-service")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env in this directory and fill in a real value."
        )
    return value


API_KEY = require_env("API_KEY")

app = FastAPI(
    title="Dependency Graph Service",
    description="Live service dependency graph, built from observed trace spans.",
    version="0.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def verify_api_key(x_api_key: str = Header(...)) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


builder = DependencyGraphBuilder()
_consumer_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup():
    global _consumer_task
    _consumer_task = asyncio.create_task(run_consumer(builder))
    logger.info("Started background Kafka consumer task for dependency graph building.")


@app.on_event("shutdown")
async def shutdown():
    if _consumer_task is not None:
        _consumer_task.cancel()


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "dependency-graph",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/graph", dependencies=[Depends(verify_api_key)])
def get_graph():
    return builder.snapshot()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006)