"""
Inventory Service
------------------
Exposes:
  - GET /health              -> liveness check
  - GET /metrics             -> Prometheus-format metrics
  - GET /inventory/{item_id} -> returns mock stock data for a given item

As of Milestone 1.H, traces are exported via OTLP/gRPC to the OTel
Collector, which forwards them to Tempo.
"""

import os
from fastapi import FastAPI, HTTPException
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

SERVICE_NAME = "inventory-service"
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
    title="Inventory Service",
    description="Mock inventory microservice for the AI Incident Commander synthetic e-commerce system.",
    version="0.4.0"
)

FastAPIInstrumentor.instrument_app(app)
Instrumentator().instrument(app).expose(app)


class InventoryResponse(BaseModel):
    item_id: str
    item_name: str
    stock_quantity: int
    warehouse_location: str
    last_updated: str


MOCK_ITEMS = {
    "item_001": {"item_name": "Wireless Mouse", "warehouse_location": "Warehouse-A"},
    "item_002": {"item_name": "Mechanical Keyboard", "warehouse_location": "Warehouse-B"},
    "item_003": {"item_name": "USB-C Hub", "warehouse_location": "Warehouse-A"},
    "item_004": {"item_name": "Laptop Stand", "warehouse_location": "Warehouse-C"},
    "item_005": {"item_name": "Webcam 1080p", "warehouse_location": "Warehouse-B"},
}


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "inventory-service",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/inventory/{item_id}", response_model=InventoryResponse)
def get_inventory(item_id: str):
    item = MOCK_ITEMS.get(item_id)

    if item is None:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")

    stock_quantity = random.randint(0, 500)

    return InventoryResponse(
        item_id=item_id,
        item_name=item["item_name"],
        stock_quantity=stock_quantity,
        warehouse_location=item["warehouse_location"],
        last_updated=datetime.utcnow().isoformat()
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)