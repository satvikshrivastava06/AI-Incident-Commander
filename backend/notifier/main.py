"""
Notifier
-----------
Polls the Incident Engine for open incidents and fires a REAL alert --
Slack, PagerDuty, or a generic webhook, your choice -- the first time
it sees each one. Enriches the alert with the Root Cause Engine's
ranking when available, so a human gets paged with "probably X,
because Y" instead of just "something's wrong."

Usage:
    python main.py --test              # fires ONE synthetic test alert and exits
    python main.py                     # real polling loop
    python main.py --min-severity high # only page for high/critical, still log the rest
"""

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("notifier")

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

STATE_FILE = os.getenv("NOTIFIER_STATE_FILE", "notified_incidents.json")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env in this directory and fill in a real value."
        )
    return value


# Chosen at import time so a bad NOTIFICATION_CHANNEL value fails
# immediately and loudly, not silently mid-poll-loop three hours in.
NOTIFICATION_CHANNEL = os.getenv("NOTIFICATION_CHANNEL", "console").lower()

if NOTIFICATION_CHANNEL == "slack":
    SLACK_WEBHOOK_URL = require_env("SLACK_WEBHOOK_URL")
elif NOTIFICATION_CHANNEL == "pagerduty":
    PAGERDUTY_ROUTING_KEY = require_env("PAGERDUTY_ROUTING_KEY")
elif NOTIFICATION_CHANNEL == "webhook":
    GENERIC_WEBHOOK_URL = require_env("GENERIC_WEBHOOK_URL")
elif NOTIFICATION_CHANNEL != "console":
    raise RuntimeError(
        f"Unknown NOTIFICATION_CHANNEL '{NOTIFICATION_CHANNEL}' -- "
        f"must be one of: console, slack, pagerduty, webhook"
    )


# ---- State persistence (dedup across restarts) ----

def load_notified_ids() -> set[str]:
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r") as f:
        return set(json.load(f))


def save_notified_ids(ids: set[str]) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(ids), f)


# ---- Channel implementations ----
# Each one matches that provider's REAL, current, documented API shape --
# not a guess. What you supply via .env is the only thing standing
# between this code and actually delivering to your account.

async def send_console(client: httpx.AsyncClient, incident: dict, enrichment: str) -> None:
    logger.warning(
        "PAGE (console channel -- no real delivery configured) -> [%s] %s: %s\n%s",
        incident["severity"].upper(), incident["service_name"], incident["title"], enrichment
    )


async def send_slack(client: httpx.AsyncClient, incident: dict, enrichment: str) -> None:
    text = (
        f":rotating_light: *[{incident['severity'].upper()}] {incident['service_name']}*\n"
        f"{incident['title']}\n\n{enrichment}"
    )
    response = await client.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10.0)
    response.raise_for_status()


async def send_pagerduty(client: httpx.AsyncClient, incident: dict, enrichment: str) -> None:
    severity_map = {"low": "info", "medium": "warning", "high": "error", "critical": "critical"}
    payload = {
        "routing_key": PAGERDUTY_ROUTING_KEY,
        "event_action": "trigger",
        # dedup_key = our own incident UUID. If this script ever sends
        # a SECOND event for the same incident (it currently doesn't --
        # each incident only gets one page, see the state file logic
        # below), PagerDuty itself would correctly treat it as an
        # update to the SAME alert instead of a brand new one. Using
        # our own stable ID here means that correctness is free,
        # whether or not this script ever grows that feature.
        "dedup_key": incident["id"],
        "payload": {
            "summary": f"[{incident['service_name']}] {incident['title']}",
            "source": "ai-incident-commander",
            "severity": severity_map.get(incident["severity"], "warning"),
            "custom_details": {
                "incident_id": incident["id"],
                "detected_at": incident.get("detected_at"),
                "root_cause_analysis": enrichment,
            },
        },
    }
    response = await client.post("https://events.pagerduty.com/v2/enqueue", json=payload, timeout=10.0)
    response.raise_for_status()


async def send_webhook(client: httpx.AsyncClient, incident: dict, enrichment: str) -> None:
    payload = {
        "incident_id": incident["id"],
        "service_name": incident["service_name"],
        "severity": incident["severity"],
        "title": incident["title"],
        "detected_at": incident.get("detected_at"),
        "root_cause_analysis": enrichment,
    }
    response = await client.post(GENERIC_WEBHOOK_URL, json=payload, timeout=10.0)
    response.raise_for_status()


CHANNEL_SENDERS = {
    "console": send_console,
    "slack": send_slack,
    "pagerduty": send_pagerduty,
    "webhook": send_webhook,
}


async def dispatch_notification(client: httpx.AsyncClient, incident: dict, enrichment: str) -> None:
    sender = CHANNEL_SENDERS[NOTIFICATION_CHANNEL]
    try:
        await sender(client, incident, enrichment)
        logger.info("Notification sent via '%s' for incident %s", NOTIFICATION_CHANNEL, incident["id"])
    except httpx.HTTPError as exc:
        # A failed page is the one failure mode in this whole retrofit
        # that deserves to be LOUD, not quietly swallowed -- unlike
        # OTLP export or a Prometheus fetch, there's no graceful
        # degradation story for "the human never found out."
        logger.error("FAILED to send notification for incident %s: %s", incident["id"], exc)


# ---- Root-cause enrichment ----

def format_enrichment(probable_causes: list[dict], open_incidents: list[dict], this_incident_id: str) -> str:
    if not probable_causes:
        return "No root-cause ranking available yet."

    top = probable_causes[0]
    lines = [f"Most likely cause: {top['service_name']} (probability {top['probability']})"]
    if top["reasons"]:
        lines.append(f"Why: {'; '.join(top['reasons'])}")

    # Lightweight grouping: if the #1 suspect ALSO has its own
    # separately-open incident right now, say so explicitly -- this
    # doesn't merge the two into one alert (that requires a real
    # correlation model, not built here), but it stops a human from
    # independently investigating two pages that are very possibly
    # the same underlying event.
    for other in open_incidents:
        if other["id"] == this_incident_id:
            continue
        if other["service_name"] == top["service_name"]:
            lines.append(
                f"NOTE: {top['service_name']} already has its own open incident "
                f"('{other['title']}') -- this may be the same underlying event."
            )
            break

    if len(probable_causes) > 1:
        others = ", ".join(f"{c['service_name']} ({c['probability']})" for c in probable_causes[1:3])
        lines.append(f"Other candidates: {others}")

    return "\n".join(lines)


async def fetch_open_incidents(client: httpx.AsyncClient, incident_engine_url: str, headers: dict) -> list[dict]:
    response = await client.get(f"{incident_engine_url}/incidents", params={"status": "open"}, headers=headers, timeout=10.0)
    response.raise_for_status()
    return response.json()


async def fetch_rootcause_enrichment(
    client: httpx.AsyncClient, rootcause_engine_url: str, headers: dict, incident: dict, open_incidents: list[dict]
) -> str:
    try:
        response = await client.post(f"{rootcause_engine_url}/rootcause/{incident['id']}", headers=headers, timeout=15.0)
        response.raise_for_status()
        data = response.json()
        return format_enrichment(data.get("probable_causes", []), open_incidents, incident["id"])
    except httpx.HTTPError as exc:
        logger.warning("Could not fetch root-cause enrichment for incident %s: %s", incident["id"], exc)
        return "Root-cause analysis unavailable (Root Cause Engine unreachable)."


# ---- Main polling loop ----

async def run_notifier(
    incident_engine_url: str,
    rootcause_engine_url: str,
    api_key: str,
    poll_interval: int,
    min_severity: str,
) -> None:
    headers = {"X-API-Key": api_key}
    notified_ids = load_notified_ids()
    min_rank = SEVERITY_RANK[min_severity]

    logger.info(
        "Notifier started -> channel=%s min_severity=%s poll_interval=%ds (already notified: %d incidents)",
        NOTIFICATION_CHANNEL, min_severity, poll_interval, len(notified_ids)
    )

    async with httpx.AsyncClient() as client:
        while True:
            try:
                open_incidents = await fetch_open_incidents(client, incident_engine_url, headers)
            except httpx.HTTPError as exc:
                logger.error("Failed to fetch open incidents: %s", exc)
                await asyncio.sleep(poll_interval)
                continue

            for incident in open_incidents:
                if incident["id"] in notified_ids:
                    continue

                if SEVERITY_RANK.get(incident["severity"], 0) < min_rank:
                    logger.info(
                        "Skipping alert for incident %s -- severity '%s' below threshold '%s'",
                        incident["id"], incident["severity"], min_severity
                    )
                    notified_ids.add(incident["id"])
                    save_notified_ids(notified_ids)
                    continue

                enrichment = await fetch_rootcause_enrichment(
                    client, rootcause_engine_url, headers, incident, open_incidents
                )
                await dispatch_notification(client, incident, enrichment)

                notified_ids.add(incident["id"])
                save_notified_ids(notified_ids)

            await asyncio.sleep(poll_interval)


async def run_test() -> None:
    fake_incident = {
        "id": "test-0000-0000-0000-000000000000",
        "service_name": "test-service",
        "title": "Test notification from notifier.py --test",
        "severity": "high",
        "detected_at": datetime.utcnow().isoformat(),
    }
    enrichment = "This is a test notification -- no real incident occurred."

    async with httpx.AsyncClient() as client:
        await dispatch_notification(client, fake_incident, enrichment)

    print(f"Test notification sent via '{NOTIFICATION_CHANNEL}' channel. Check your configured destination.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll for open incidents and send real alerts.")
    parser.add_argument("--test", action="store_true", help="Send one synthetic test notification and exit")
    parser.add_argument("--incident-engine-url", default="http://localhost:8007")
    parser.add_argument("--rootcause-engine-url", default="http://localhost:8008")
    parser.add_argument("--poll-interval", type=int, default=30, help="Seconds between polls (default: 30)")
    parser.add_argument(
        "--min-severity", default="medium", choices=["low", "medium", "high", "critical"],
        help="Minimum severity that triggers a real page; lower severities are still logged (default: medium)"
    )
    args = parser.parse_args()

    if args.test:
        # Deliberately does NOT require API_KEY -- test mode never
        # calls incident-engine or rootcause-engine, only the
        # notification channel itself, so it shouldn't demand a
        # credential it doesn't need just to verify Slack/PagerDuty
        # delivery works.
        asyncio.run(run_test())
        return

    api_key = require_env("API_KEY")
    asyncio.run(run_notifier(
        args.incident_engine_url, args.rootcause_engine_url, api_key,
        args.poll_interval, args.min_severity,
    ))


if __name__ == "__main__":
    main()