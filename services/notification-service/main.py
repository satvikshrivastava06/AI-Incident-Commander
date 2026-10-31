"""
Notification Service
-----------------------
Exposes:
  - GET /health   -> liveness check
  - GET /metrics  -> Prometheus-format metrics
  - POST /notify  -> accepts a notification request and "publishes" it
                      to a message queue (stubbed for now)

As of Milestone 1.H, traces are exported via OTLP/gRPC to the OTel
Collector, which forwards them to Tempo.
"""

import os
from fastapi import FastAPI
from pydantic import BaseModel, Field
from datetime import datetime
import logging
import uuid

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from prometheus_fastapi_instrumentator import Instrumentator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notification-service")

SERVICE_NAME = "notification-service"
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
    title="Notification Service",
    description="Mock notification microservice for the AI Incident Commander synthetic e-commerce system.",
    version="0.4.0"
)

FastAPIInstrumentor.instrument_app(app)
Instrumentator().instrument(app).expose(app)


class NotificationRequest(BaseModel):
    user_id: str = Field(..., description="The user to notify")
    message: str = Field(..., min_length=1, description="The notification content")
    channel: str = Field(default="email", description="Delivery channel: email, sms, or push")


class NotificationResponse(BaseModel):
    notification_id: str
    status: str
    queued_at: str


async def publish_to_queue(routing_key: str, payload: dict) -> None:
    logger.info(
        "STUB PUBLISH -> exchange='notifications', routing_key='%s', payload=%s",
        routing_key,
        payload
    )


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "notification-service",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/notify", response_model=NotificationResponse)
async def notify(request: NotificationRequest):
    notification_id = str(uuid.uuid4())

    await publish_to_queue(
        routing_key=f"notify.{request.channel}",
        payload={
            "notification_id": notification_id,
            "user_id": request.user_id,
            "message": request.message,
            "channel": request.channel,
        }
    )

    return NotificationResponse(
        notification_id=notification_id,
        status="queued",
        queued_at=datetime.utcnow().isoformat()
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)