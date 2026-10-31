"""
Z-Score Anomaly Detector
----------------------------
Polls Prometheus for each service's current average request latency,
maintains a rolling window of recent samples per service, and flags a
new sample as anomalous when it deviates too many standard deviations
from that service's own recent baseline. Reports flagged anomalies to
the Incident Engine.

Usage:
    python zscore_detector.py
    python zscore_detector.py --threshold 2.5 --window-size 20 --poll-interval 15
"""

import argparse
import asyncio
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from statistics import mean, stdev

import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("zscore-detector")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env in this directory and fill in a real value."
        )
    return value


# CHANGED: incident-engine now requires this on every call.
API_KEY = require_env("API_KEY")
OUTGOING_HEADERS = {"X-API-Key": API_KEY}

PROMETHEUS_USER = os.getenv("PROMETHEUS_USER", "admin")
PROMETHEUS_PASSWORD = require_env("PROMETHEUS_PASSWORD")
PROMETHEUS_AUTH = (PROMETHEUS_USER, PROMETHEUS_PASSWORD)

PROMETHEUS_URL_DEFAULT = "http://localhost:9090"
INCIDENT_ENGINE_URL_DEFAULT = "http://localhost:8007"

LATENCY_QUERY = (
    'sum(rate(http_request_duration_seconds_sum[1m])) by (job) '
    '/ '
    'sum(rate(http_request_duration_seconds_count[1m])) by (job)'
)


@dataclass
class ServiceWindow:
    samples: deque = field(default_factory=lambda: deque(maxlen=30))


async def query_prometheus(client: httpx.AsyncClient, prometheus_url: str, query: str) -> dict[str, float]:
    response = await client.get(
        f"{prometheus_url}/api/v1/query",
        params={"query": query},
        auth=PROMETHEUS_AUTH,
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json()

    results = {}
    for item in data.get("data", {}).get("result", []):
        service = item["metric"].get("job")
        _, value_str = item["value"]
        if service is not None:
            try:
                results[service] = float(value_str)
            except ValueError:
                continue
    return results


def check_for_anomaly(window: ServiceWindow, new_value: float, threshold: float, min_samples: int) -> float | None:
    if len(window.samples) < min_samples:
        return None

    baseline_mean = mean(window.samples)
    baseline_stdev = stdev(window.samples)

    if baseline_stdev == 0:
        return float("inf") if new_value != baseline_mean else 0.0

    z_score = (new_value - baseline_mean) / baseline_stdev
    return z_score if abs(z_score) >= threshold else None


def severity_for_zscore(z_score: float) -> str:
    magnitude = abs(z_score)
    if magnitude >= 5:
        return "critical"
    if magnitude >= 4:
        return "high"
    return "medium"


async def report_incident(
    client: httpx.AsyncClient,
    incident_engine_url: str,
    service: str,
    value: float,
    z_score: float,
    baseline_mean: float,
    baseline_stdev: float,
) -> None:
    payload = {
        "service_name": service,
        "title": f"Elevated latency detected on {service}",
        "description": (
            f"zscore_detector.py flagged an anomaly: current avg latency "
            f"{value:.4f}s, baseline mean {baseline_mean:.4f}s, "
            f"baseline stdev {baseline_stdev:.4f}s, z-score {z_score:.2f}."
        ),
        "severity": severity_for_zscore(z_score),
    }

    try:
        # CHANGED: now sends OUTGOING_HEADERS.
        response = await client.post(
            f"{incident_engine_url}/incidents", json=payload, headers=OUTGOING_HEADERS, timeout=10.0
        )
        response.raise_for_status()
        incident = response.json()
        logger.info(
            "Reported to Incident Engine -> incident_id=%s (%s)",
            incident["id"],
            "new incident" if response.status_code == 201 else "existing open incident",
        )
    except httpx.HTTPError as exc:
        logger.error("Failed to report incident to Incident Engine: %s", exc)


async def run_detector(
    prometheus_url: str,
    incident_engine_url: str,
    threshold: float,
    window_size: int,
    min_samples: int,
    poll_interval: int,
) -> None:
    windows: dict[str, ServiceWindow] = {}

    async with httpx.AsyncClient() as client:
        logger.info(
            "Z-score detector started -> prometheus=%s incident_engine=%s threshold=%.1f window_size=%d poll_interval=%ds",
            prometheus_url, incident_engine_url, threshold, window_size, poll_interval
        )

        while True:
            try:
                latest_values = await query_prometheus(client, prometheus_url, LATENCY_QUERY)
            except httpx.HTTPError as exc:
                logger.error("Failed to query Prometheus: %s", exc)
                await asyncio.sleep(poll_interval)
                continue

            for service, value in latest_values.items():
                window = windows.setdefault(service, ServiceWindow(samples=deque(maxlen=window_size)))

                z_score = check_for_anomaly(window, value, threshold, min_samples)
                if z_score is not None:
                    baseline_mean = mean(window.samples)
                    baseline_stdev = stdev(window.samples) if len(window.samples) > 1 else 0.0

                    logger.warning(
                        "ANOMALY DETECTED -> service=%s latency=%.4fs z_score=%.2f baseline_mean=%.4fs baseline_stdev=%.4fs",
                        service, value, z_score, baseline_mean, baseline_stdev,
                    )

                    await report_incident(
                        client, incident_engine_url, service, value, z_score, baseline_mean, baseline_stdev
                    )
                else:
                    logger.info("service=%s latency=%.4fs (normal)", service, value)

                window.samples.append(value)

            await asyncio.sleep(poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rolling z-score anomaly detector for service latency.")
    parser.add_argument("--prometheus-url", default=PROMETHEUS_URL_DEFAULT, help="Prometheus base URL")
    parser.add_argument("--incident-engine-url", default=INCIDENT_ENGINE_URL_DEFAULT, help="Incident Engine base URL")
    parser.add_argument("--threshold", type=float, default=3.0, help="Z-score threshold to flag as anomalous (default: 3.0)")
    parser.add_argument("--window-size", type=int, default=30, help="Number of samples to keep per service (default: 30)")
    parser.add_argument("--min-samples", type=int, default=10, help="Minimum samples before evaluating anomalies (default: 10)")
    parser.add_argument("--poll-interval", type=int, default=15, help="Seconds between polls (default: 15)")
    args = parser.parse_args()

    asyncio.run(run_detector(
        args.prometheus_url, args.incident_engine_url,
        args.threshold, args.window_size, args.min_samples, args.poll_interval
    ))


if __name__ == "__main__":
    main()