"""
Recommendation Service
------------------------
Exposes:
  - GET /health                      -> liveness check
  - GET /metrics                     -> Prometheus-format metrics
  - GET /recommendations/{user_id}   -> returns a mock list of recommended items

As of Milestone 1.H, traces are exported via OTLP/gRPC to the OTel
Collector, which forwards them to Tempo.
"""

import os
from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime
import random

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from prometheus_fastapi_instrumentator import Instrumentator

SERVICE_NAME = "recommendation-service"
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
    title="Recommendation Service",
    description="Mock recommendation microservice for the AI Incident Commander synthetic e-commerce system.",
    version="0.4.0"
)

FastAPIInstrumentor.instrument_app(app)
Instrumentator().instrument(app).expose(app)


class RecommendedItem(BaseModel):
    item_id: str
    item_name: str
    score: float


class RecommendationResponse(BaseModel):
    user_id: str
    recommendations: list[RecommendedItem]
    generated_at: str


CATALOG = [
    {"item_id": "item_001", "item_name": "Wireless Mouse"},
    {"item_id": "item_002", "item_name": "Mechanical Keyboard"},
    {"item_id": "item_003", "item_name": "USB-C Hub"},
    {"item_id": "item_004", "item_name": "Laptop Stand"},
    {"item_id": "item_005", "item_name": "Webcam 1080p"},
]


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "recommendation-service",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/recommendations/{user_id}", response_model=RecommendationResponse)
def get_recommendations(user_id: str):
    picks = random.sample(CATALOG, k=min(3, len(CATALOG)))

    recommendations = [
        RecommendedItem(
            item_id=item["item_id"],
            item_name=item["item_name"],
            score=round(random.uniform(0.5, 0.99), 2)
        )
        for item in picks
    ]

    recommendations.sort(key=lambda r: r.score, reverse=True)

    return RecommendationResponse(
        user_id=user_id,
        recommendations=recommendations,
        generated_at=datetime.utcnow().isoformat()
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)