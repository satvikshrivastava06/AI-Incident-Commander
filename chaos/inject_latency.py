"""
Inject Latency — Chaos Tool
------------------------------
Adds artificial network latency to a running Pod's own network
interface using Linux's `tc` (traffic control) + `netem` (network
emulator) queuing discipline -- the same low-level mechanism real
chaos-engineering tools (Chaos Mesh, Gremlin, etc.) rely on under the
hood, just invoked directly here instead of through a dedicated
chaos-mesh operator.

Unlike killing a Pod (Step 1.29), this doesn't crash anything -- it
degrades ONE Pod's network responsiveness for a fixed duration, then
automatically reverts it. This is what lets you observe how latency
injected at one point in the call graph (e.g. payment-service) shows
up as elevated latency everywhere UPSTREAM of it too (e.g. gateway's
/checkout, since it awaits payment-service's response) -- exactly the
kind of propagation pattern your dependency-graph engine (Milestone
1.M, coming up next) will eventually need to reason about.

Requires the NET_ADMIN capability granted in the Helm chart update
above -- without it, every `tc` call here fails with "Operation not
permitted."

Usage:
    python inject_latency.py --service payment-service --delay-ms 800 --duration 60
    python inject_latency.py --service inventory-service --delay-ms 2000 --duration 30
"""

import argparse
import json
import subprocess
import sys
import time

TARGET_SERVICES = [
    "inventory-service",
    "auth-service",
    "payment-service",
    "recommendation-service",
    "notification-service",
    "gateway",
]

# The network interface name inside a Pod's network namespace. Both
# kind's default CNI (kindnet) and minikube's default CNI name a
# Pod's primary interface "eth0". If you're running a different CNI
# that names things differently, override this constant.
POD_INTERFACE = "eth0"


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


def exec_in_pod(pod_name: str, namespace: str, command: list[str]) -> subprocess.CompletedProcess:
    return run_kubectl(
        ["exec", pod_name, "-n", namespace, "--", *command],
        check=False,
    )


def ensure_tc_installed(pod_name: str, namespace: str) -> None:
    """
    Our service images are built from python:3.11-slim, which doesn't
    ship `tc` by default. Rather than permanently bloating every
    service's Dockerfile with a networking tool it only ever needs
    during deliberate chaos testing, we install it on demand, inside
    the already-running container, the moment we actually need it.
    """
    check = exec_in_pod(pod_name, namespace, ["which", "tc"])
    if check.returncode == 0:
        return

    print(f"'tc' not found in {pod_name}, installing iproute2...")
    install = exec_in_pod(
        pod_name, namespace,
        ["sh", "-c", "apt-get update -qq && apt-get install -y -qq iproute2"]
    )
    if install.returncode != 0:
        print(f"ERROR: failed to install iproute2 in {pod_name}:\n{install.stderr}", file=sys.stderr)
        sys.exit(1)


def add_latency(pod_name: str, namespace: str, delay_ms: int) -> None:
    result = exec_in_pod(
        pod_name, namespace,
        ["tc", "qdisc", "add", "dev", POD_INTERFACE, "root", "netem", "delay", f"{delay_ms}ms"]
    )
    if result.returncode != 0:
        print(f"ERROR: failed to add latency rule:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def remove_latency(pod_name: str, namespace: str) -> None:
    # Deliberately don't check the return code here -- if this runs
    # during cleanup after something already went wrong, the qdisc
    # rule might not exist to remove, and that's fine; attempting
    # cleanup unconditionally is safer than skipping it.
    exec_in_pod(pod_name, namespace, ["tc", "qdisc", "del", "dev", POD_INTERFACE, "root"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject artificial network latency into a running Pod.")
    parser.add_argument("--service", required=True, choices=TARGET_SERVICES, help="Target service")
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace (default: default)")
    parser.add_argument("--delay-ms", type=int, default=500, help="Latency to add, in milliseconds (default: 500)")
    parser.add_argument("--duration", type=int, default=60, help="How long to hold the latency, in seconds (default: 60)")
    args = parser.parse_args()

    pod_name = get_first_pod(args.service, args.namespace)
    print(f"Targeting Pod '{pod_name}' (service: {args.service})")

    ensure_tc_installed(pod_name, args.namespace)

    print(f"Adding {args.delay_ms}ms of latency on interface {POD_INTERFACE} for {args.duration}s...")
    add_latency(pod_name, args.namespace, args.delay_ms)

    try:
        remaining = args.duration
        while remaining > 0:
            print(f"  ...{remaining}s remaining (Ctrl+C to stop early)")
            step = min(5, remaining)
            time.sleep(step)
            remaining -= step
    except KeyboardInterrupt:
        print("\nInterrupted -- reverting early.")
    finally:
        print(f"Removing latency rule from '{pod_name}'...")
        remove_latency(pod_name, args.namespace)
        print("Done. Network latency reverted to normal.")


if __name__ == "__main__":
    main()