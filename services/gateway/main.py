"""
Gateway Service
-----------------
The entry point into our synthetic e-commerce system. This is the
ONLY service the frontend talks to directly -- it fans out to every
other backend service on the frontend's behalf.

Exposes:
  - GET /health     -> liveness check
  - GET /metrics    -> Prometheus-format metrics
  - POST /checkout  -> orchestrates: login -> charge -> check inventory
                        -> get recommendations, and returns one combined
                        response

As of Milestone 1.H, traces are exported via OTLP/gRPC to the OTel
Collector (instead of just printing to this service's own console),
which in turn forwards them to Tempo for storage and querying.
"""

import os
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
import httpx

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from prometheus_fastapi_instrumentator import Instrumentator

SERVICE_NAME = "gateway"
DEPLOYMENT_ID = os.getenv("DEPLOYMENT_ID", "local")
resource = Resource.create({"service.name": SERVICE_NAME, "deployment.id": DEPLOYMENT_ID})

# Where the OTel Collector is listening for incoming spans. Locally
# (running `uvicorn` directly) this defaults to localhost; inside
# Docker Compose (Step 1.20) it's overridden to "otel-collector:4317".
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
    title="Gateway Service",
    description="Entry point / orchestrator for the AI Incident Commander synthetic e-commerce system.",
    version="0.5.0"
)

FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()
Instrumentator().instrument(app).expose(app)

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:8001")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8002")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8000")
RECOMMENDATION_SERVICE_URL = os.getenv("RECOMMENDATION_SERVICE_URL", "http://localhost:8003")

http_client = httpx.AsyncClient(timeout=10.0)


class CheckoutRequest(BaseModel):
    username: str = Field(..., description="Username to log in with")
    password: str = Field(..., description="Password to log in with")
    item_id: str = Field(..., description="Item being purchased")
    amount: float = Field(..., gt=0, description="Amount to charge")


class CheckoutResponse(BaseModel):
    status: str
    user_id: str
    transaction_id: str
    item: dict
    recommendations: list
    completed_at: str


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "gateway",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/checkout", response_model=CheckoutResponse)
async def checkout(request: CheckoutRequest):
    try:
        login_resp = await http_client.post(
            f"{AUTH_SERVICE_URL}/login",
            json={"username": request.username, "password": request.password}
        )
        login_resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"auth-service unreachable or failed: {exc}")

    auth_data = login_resp.json()
    user_id = auth_data["user_id"]

    try:
        charge_resp = await http_client.post(
            f"{PAYMENT_SERVICE_URL}/charge",
            json={"user_id": user_id, "amount": request.amount, "currency": "USD"}
        )
        charge_resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"payment-service declined or unreachable: {exc}")

    charge_data = charge_resp.json()

    async def fetch_inventory():
        resp = await http_client.get(f"{INVENTORY_SERVICE_URL}/inventory/{request.item_id}")
        resp.raise_for_status()
        return resp.json()

    async def fetch_recommendations():
        resp = await http_client.get(f"{RECOMMENDATION_SERVICE_URL}/recommendations/{user_id}")
        resp.raise_for_status()
        return resp.json()

    try:
        inventory_data, recommendation_data = await asyncio.gather(
            fetch_inventory(),
            fetch_recommendations()
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"downstream service failed: {exc}")

    return CheckoutResponse(
        status="success",
        user_id=user_id,
        transaction_id=charge_data["transaction_id"],
        item=inventory_data,
        recommendations=recommendation_data["recommendations"],
        completed_at=datetime.utcnow().isoformat()
    )


@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)