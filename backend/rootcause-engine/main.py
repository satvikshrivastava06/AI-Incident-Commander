"""
Root Cause Engine
--------------------
Combines the dependency graph, live Prometheus signals, and current
incident-engine state to produce a ranked, EXPLAINED list of probable
root causes for a given incident.
"""

import logging
import os
from datetime import datetime, timedelta
from statistics import mean, stdev

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from rules import rank_probable_causes

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rootcause-engine")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env in this directory and fill in a real value."
        )
    return value


API_KEY = require_env("API_KEY")
OUTGOING_HEADERS = {"X-API-Key": API_KEY}

PROMETHEUS_USER = os.getenv("PROMETHEUS_USER", "admin")
PROMETHEUS_PASSWORD = require_env("PROMETHEUS_PASSWORD")
PROMETHEUS_AUTH = (PROMETHEUS_USER, PROMETHEUS_PASSWORD)

# CHANGED: these three were hardcoded constants. Now configurable via
# env, with the old hardcoded values kept as defaults -- so running
# this directly with `python main.py` on your own machine (no .env
# overrides) behaves EXACTLY as before, while the Helm chart can now
# override all three to their real in-cluster/host addresses.
INCIDENT_ENGINE_URL = os.getenv("INCIDENT_ENGINE_URL", "http://localhost:8007")
DEPENDENCY_GRAPH_URL = os.getenv("DEPENDENCY_GRAPH_URL", "http://localhost:8006")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

app = FastAPI(
    title="Root Cause Engine",
    description="Rule-based root-cause ranking for incidents recognized by the AI Incident Commander platform.",
    version="0.7.0"
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


LATENCY_QUERY = (
    'sum(rate(http_request_duration_seconds_sum[1m])) by (job) '
    '/ '
    'sum(rate(http_request_duration_seconds_count[1m])) by (job)'
)

BASELINE_WINDOW_MINUTES = 15
BASELINE_STEP_SECONDS = 15
MIN_BASELINE_SAMPLES = 5


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "rootcause-engine",
        "timestamp": datetime.utcnow().isoformat()
    }


async def compute_latency_zscores(client: httpx.AsyncClient) -> dict[str, float]:
    now = datetime.utcnow()
    baseline_start = now - timedelta(minutes=BASELINE_WINDOW_MINUTES)

    try:
        range_resp = await client.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={
                "query": LATENCY_QUERY,
                "start": baseline_start.timestamp(),
                "end": now.timestamp(),
                "step": f"{BASELINE_STEP_SECONDS}s",
            },
            auth=PROMETHEUS_AUTH,
            timeout=15.0,
        )
        range_resp.raise_for_status()
        range_data = range_resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Could not fetch latency history from Prometheus: %s", exc)
        return {}

    zscores: dict[str, float] = {}
    for series in range_data.get("data", {}).get("result", []):
        service = series["metric"].get("job")
        if service is None:
            continue

        values = []
        for _, value_str in series.get("values", []):
            try:
                values.append(float(value_str))
            except ValueError:
                continue

        if len(values) < MIN_BASELINE_SAMPLES:
            continue

        *baseline_values, current_value = values
        if len(baseline_values) < 2:
            continue

        baseline_mean = mean(baseline_values)
        baseline_stdev = stdev(baseline_values)

        if baseline_stdev == 0:
            zscores[service] = 0.0 if current_value == baseline_mean else 10.0
            continue

        zscores[service] = (current_value - baseline_mean) / baseline_stdev

    return zscores


@app.post("/rootcause/{incident_id}", dependencies=[Depends(verify_api_key)])
async def get_root_cause(incident_id: str):
    async with httpx.AsyncClient() as client:
        incident_resp = await client.get(
            f"{INCIDENT_ENGINE_URL}/incidents/{incident_id}", headers=OUTGOING_HEADERS, timeout=10.0
        )
        if incident_resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
        incident_resp.raise_for_status()
        incident = incident_resp.json()
        affected_service = incident["service_name"]

        graph_resp = await client.get(f"{DEPENDENCY_GRAPH_URL}/graph", headers=OUTGOING_HEADERS, timeout=10.0)
        graph_resp.raise_for_status()
        graph = graph_resp.json()

        predecessors = [e["source"] for e in graph["edges"] if e["target"] == affected_service]
        successors = [e["target"] for e in graph["edges"] if e["source"] == affected_service]

        open_resp = await client.get(
            f"{INCIDENT_ENGINE_URL}/incidents", params={"status": "open"}, headers=OUTGOING_HEADERS, timeout=10.0
        )
        open_resp.raise_for_status()
        open_incident_services = {
            item["service_name"] for item in open_resp.json() if item["id"] != incident_id
        }

        latency_zscores = await compute_latency_zscores(client)

        ranked_causes = rank_probable_causes(
            affected_service=affected_service,
            predecessors=predecessors,
            successors=successors,
            open_incident_services=open_incident_services,
            latency_zscores=latency_zscores,
        )

        try:
            await client.post(
                f"{INCIDENT_ENGINE_URL}/incidents/{incident_id}/predictions",
                json={"ranked_causes": ranked_causes},
                headers=OUTGOING_HEADERS,
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            logger.warning("Failed to record prediction for incident %s: %s", incident_id, exc)

    return {
        "incident_id": incident_id,
        "affected_service": affected_service,
        "probable_causes": ranked_causes,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8008)