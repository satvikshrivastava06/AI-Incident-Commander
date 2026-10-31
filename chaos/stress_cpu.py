"""
Stress CPU — Chaos Tool
---------------------------
Burns CPU inside a running Pod for a fixed duration, using nothing but
the Python interpreter already present in every one of our service
images -- no extra tooling to install, unlike Step 1.30's tc/iproute2
requirement, and no special Linux capability needed either (a process
consuming its own CPU time requires no elevated permissions at all).

This also happens to be a clean, deterministic way to trigger the
HorizontalPodAutoscaler built in Milestone 1.K: instead of blasting
HTTP traffic and hoping it generates enough real CPU load, this drives
CPU usage directly and predictably.

Usage:
    python stress_cpu.py --service payment-service --duration 60
    python stress_cpu.py --service payment-service --duration 90 --workers 4
"""

import argparse
import json
import subprocess
import sys

TARGET_SERVICES = [
    "inventory-service",
    "auth-service",
    "payment-service",
    "recommendation-service",
    "notification-service",
    "gateway",
]

# A deliberately pointless, CPU-bound computation. It doesn't matter
# WHAT work is being done -- only that the CPU stays continuously busy
# and never blocks on I/O (which wouldn't stress the CPU at all).
BURN_CODE_TEMPLATE = """
import time, multiprocessing

def burn(duration):
    end = time.time() + duration
    x = 0.0
    while time.time() < end:
        x = (x * x + 1.0) if x < 1e6 else 0.0

if __name__ == "__main__":
    procs = [multiprocessing.Process(target=burn, args=({duration},)) for _ in range({workers})]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
"""


def run_kubectl(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["kubectl", *args],
            capture_output=True,
            text=True,
            check=check,
        )
    except FileNotFoundError:
        print("ERROR: kubectl not found on PATH. Is it installed?", file=sys.stderr)
        sys.exit(1)


def get_first_pod(service: str, namespace: str) -> str:
    result = run_kubectl([
        "get", "pods",
        "-n", namespace,
        "-l", f"app={service}",
        "-o", "json",
    ])
    data = json.loads(result.stdout)
    items = data.get("items", [])
    if not items:
        print(f"ERROR: no running Pods found for service '{service}'.", file=sys.stderr)
        sys.exit(1)
    return items[0]["metadata"]["name"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Burn CPU inside a running Pod for a fixed duration.")
    parser.add_argument("--service", required=True, choices=TARGET_SERVICES, help="Target service")
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace (default: default)")
    parser.add_argument("--duration", type=int, default=30, help="How long to burn CPU, in seconds (default: 30)")
    parser.add_argument("--workers", type=int, default=2, help="Number of CPU-burning worker processes (default: 2)")
    args = parser.parse_args()

    pod_name = get_first_pod(args.service, args.namespace)
    print(f"Targeting Pod '{pod_name}' (service: {args.service})")
    print(f"Burning CPU with {args.workers} worker process(es) for {args.duration}s...")
    print("(This call blocks until the burn finishes -- watch `kubectl top pod` or Grafana in another terminal.)")

    burn_code = BURN_CODE_TEMPLATE.format(duration=args.duration, workers=args.workers)

    result = run_kubectl(
        ["exec", pod_name, "-n", args.namespace, "--", "python3", "-c", burn_code],
        check=False,
    )

    if result.returncode != 0:
        print(f"ERROR: CPU burn failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"Done. CPU burn on '{pod_name}' finished after {args.duration}s.")


if __name__ == "__main__":
    main()