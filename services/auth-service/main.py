"""
Auth Service
------------
Exposes:
  - GET /health   -> liveness check
  - GET /metrics  -> Prometheus-format metrics
  - POST /login   -> accepts username/password, returns a mock access token

As of Milestone 1.H, traces are exported via OTLP/gRPC to the OTel
Collector, which forwards them to Tempo.
"""

import os
from fastapi import FastAPI
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from prometheus_fastapi_instrumentator import Instrumentator

SERVICE_NAME = "auth-service"
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
    title="Auth Service",
    description="Mock authentication microservice for the AI Incident Commander synthetic e-commerce system.",
    version="0.4.0"
)

FastAPIInstrumentor.instrument_app(app)
Instrumentator().instrument(app).expose(app)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, description="The username attempting to log in")
    password: str = Field(..., min_length=1, description="The password (never actually checked here)")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user_id: str
    issued_at: str


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "auth-service",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/login", response_model=TokenResponse)
def login(credentials: LoginRequest):
    user_id = f"user_{abs(hash(credentials.username)) % 10000}"
    fake_token = str(uuid.uuid4())

    return TokenResponse(
        access_token=fake_token,
        token_type="bearer",
        expires_in=3600,
        user_id=user_id,
        issued_at=datetime.utcnow().isoformat()
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)