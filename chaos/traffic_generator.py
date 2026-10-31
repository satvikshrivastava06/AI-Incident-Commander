"""
Traffic Generator
-------------------
Generates realistic synthetic load against the gateway's /checkout
endpoint by simulating many independent "users" arriving at random
intervals and attempting a checkout.

This is NOT a simple for-loop hitting the endpoint at a fixed rate.
Real user traffic doesn't arrive evenly spaced -- it arrives as a
random (Poisson-like) process, with some quiet gaps and some bursts.
We model that using an exponential distribution for the time BETWEEN
request arrivals, which is the standard way to simulate arrival
processes in queuing theory and load testing.

Usage:
    python traffic_generator.py --rate 5 --duration 120
    python traffic_generator.py --rate 2 --duration 0   # 0 = run forever, Ctrl+C to stop
"""

import argparse
import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("traffic-generator")


# A small pool of fake usernames and item IDs to randomize across,
# so requests look like they're coming from different real users
# hitting different products -- not the same single hardcoded call
# repeated forever.
FAKE_USERNAMES = [
    "alice", "bob", "carla", "dev_user", "priya",
    "raj_shop", "meena_k", "arjun99", "neha_b", "sam_t"
]

FAKE_ITEM_IDS = [
    "item_001", "item_002", "item_003", "item_004", "item_005",
    "item_999",  # deliberately invalid -- exercises the error path too
]


@dataclass
class TrafficStats:
    """
    Tracks running totals as the generator sends requests, so we can
    print a live summary instead of a wall of raw log lines with no
    way to see overall health at a glance.
    """
    total_sent: int = 0
    total_success: int = 0
    total_declined: int = 0       # payment-service's simulated 402
    total_gateway_error: int = 0  # 502 from the gateway (downstream failure)
    total_timeout: int = 0
    total_other_error: int = 0
    latencies_ms: list = field(default_factory=list)

    def record_success(self, latency_ms: float):
        self.total_sent += 1
        self.total_success += 1
        self.latencies_ms.append(latency_ms)

    def record_declined(self):
        self.total_sent += 1
        self.total_declined += 1

    def record_gateway_error(self):
        self.total_sent += 1
        self.total_gateway_error += 1

    def record_timeout(self):
        self.total_sent += 1
        self.total_timeout += 1

    def record_other_error(self):
        self.total_sent += 1
        self.total_other_error += 1

    def summary(self) -> str:
        if self.latencies_ms:
            avg_latency = sum(self.latencies_ms) / len(self.latencies_ms)
            avg_latency_str = f"{avg_latency:.0f}ms"
        else:
            avg_latency_str = "n/a"

        return (
            f"sent={self.total_sent} "
            f"success={self.total_success} "
            f"declined={self.total_declined} "
            f"gateway_error={self.total_gateway_error} "
            f"timeout={self.total_timeout} "
            f"other_error={self.total_other_error} "
            f"avg_latency={avg_latency_str}"
        )


async def simulate_one_checkout(client: httpx.AsyncClient, gateway_url: str, stats: TrafficStats) -> None:
    """
    Simulates a single user attempting a checkout.

    Picks a random fake user, random item, random dollar amount, and
    sends it to the gateway's /checkout endpoint. All the different
    failure modes the gateway can return (validation error, downstream
    502, timeout) are handled here individually and recorded into
    `stats`, rather than treated as one generic "it failed" bucket --
    this distinction matters once you build monitoring on top of this
    traffic later.
    """
    username = random.choice(FAKE_USERNAMES)
    item_id = random.choice(FAKE_ITEM_IDS)
    amount = round(random.uniform(5.0, 250.0), 2)

    payload = {
        "username": username,
        "password": "synthetic_password",  # auth-service never checks this for real
        "item_id": item_id,
        "amount": amount,
    }

    start_time = time.perf_counter()

    try:
        response = await client.post(f"{gateway_url}/checkout", json=payload, timeout=10.0)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        if response.status_code == 200:
            stats.record_success(elapsed_ms)
            logger.info(
                "CHECKOUT OK  user=%s item=%s amount=%.2f latency=%.0fms",
                username, item_id, amount, elapsed_ms
            )
        elif response.status_code == 402:
            stats.record_declined()
            logger.warning(
                "CHECKOUT DECLINED  user=%s item=%s amount=%.2f",
                username, item_id, amount
            )
        elif response.status_code == 502:
            stats.record_gateway_error()
            logger.warning(
                "CHECKOUT GATEWAY_ERROR  user=%s item=%s detail=%s",
                username, item_id, response.text[:200]
            )
        else:
            stats.record_other_error()
            logger.warning(
                "CHECKOUT UNEXPECTED_STATUS=%s user=%s item=%s body=%s",
                response.status_code, username, item_id, response.text[:200]
            )

    except httpx.TimeoutException:
        stats.record_timeout()
        logger.error("CHECKOUT TIMEOUT  user=%s item=%s", username, item_id)

    except httpx.HTTPError as exc:
        stats.record_other_error()
        logger.error("CHECKOUT NETWORK_ERROR  user=%s item=%s error=%s", username, item_id, exc)


async def run_traffic_loop(gateway_url: str, rate_per_second: float, duration_seconds: int, stats: TrafficStats) -> None:
    """
    Continuously spawns checkout attempts at randomized intervals until
    `duration_seconds` has elapsed (or forever, if duration_seconds <= 0).

    Instead of `await asyncio.sleep(1 / rate)` in a tight loop (which
    creates perfectly evenly-spaced requests -- unrealistic), we draw
    each inter-arrival gap from an EXPONENTIAL distribution. This is
    the standard model for a "Poisson process": events that occur
    independently at a known average rate, but with random gaps
    between them -- exactly how real user traffic behaves.

    Each simulated checkout is launched as its OWN asyncio task
    (fire-and-forget, tracked in `in_flight`) rather than awaited
    one-by-one. This means slow or hanging requests don't block the
    generator from continuing to send new traffic -- just like real
    concurrent users wouldn't wait for each other.
    """
    start_time = time.monotonic()
    in_flight: list[asyncio.Task] = []

    async with httpx.AsyncClient() as client:
        while True:
            if duration_seconds > 0 and (time.monotonic() - start_time) >= duration_seconds:
                break

            # Exponential inter-arrival time: on average, 1/rate_per_second
            # seconds between requests, but randomized around that average.
            gap_seconds = random.expovariate(rate_per_second)
            await asyncio.sleep(gap_seconds)

            task = asyncio.create_task(simulate_one_checkout(client, gateway_url, stats))
            in_flight.append(task)

            # Periodically clean up finished tasks so `in_flight` doesn't
            # grow forever during a long-running session.
            in_flight = [t for t in in_flight if not t.done()]

            # Print a running summary every 10 requests sent, so you can
            # watch the system's health live without waiting for the end.
            if stats.total_sent > 0 and stats.total_sent % 10 == 0:
                logger.info("--- SUMMARY: %s ---", stats.summary())

        # Once the time limit is hit, wait for any still-in-flight
        # requests to finish before we print the final summary --
        # otherwise we'd undercount successes that were still pending.
        if in_flight:
            logger.info("Waiting for %d in-flight requests to finish...", len(in_flight))
            await asyncio.gather(*in_flight, return_exceptions=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic checkout traffic against the gateway.")
    parser.add_argument(
        "--gateway-url",
        default="http://localhost:8005",
        help="Base URL of the gateway service (default: http://localhost:8005)"
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=2.0,
        help="Average requests per second (default: 2.0)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="How long to run in seconds. Use 0 to run forever until Ctrl+C (default: 60)"
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    stats = TrafficStats()

    logger.info(
        "Starting traffic generator -> target=%s rate=%.1f req/s duration=%s",
        args.gateway_url,
        args.rate,
        "infinite" if args.duration <= 0 else f"{args.duration}s"
    )

    try:
        await run_traffic_loop(args.gateway_url, args.rate, args.duration, stats)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        logger.info("=== FINAL SUMMARY: %s ===", stats.summary())


if __name__ == "__main__":
    asyncio.run(main())