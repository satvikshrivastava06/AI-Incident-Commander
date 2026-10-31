"""
Kill Pod — Chaos Tool
------------------------
Randomly kills one Pod from your running services, so you can watch
Kubernetes' self-healing behavior in real time: the Deployment's
ReplicaSet notices the actual replica count no longer matches what's
declared, and creates a replacement Pod automatically -- no human
intervention required.

This deliberately shells out to `kubectl` rather than using a
Kubernetes client library -- `kubectl delete pod` is the exact command
being wrapped here, just with random target selection and some
safety rails layered on top.

Usage:
    python kill_pod.py                              # kill one random Pod from a random target service
    python kill_pod.py --service payment-service     # kill a random Pod from a specific service
    python kill_pod.py --include-stateful             # allow postgres/redis as possible targets too
    python kill_pod.py --force                        # skip the graceful termination period
    python kill_pod.py --dry-run                      # show what WOULD be killed, without doing it
"""

import argparse
import json
import random
import subprocess
import sys

# Stateless app services -- the default, safe target pool. All backed
# by Deployments, so killing one Pod is expected to self-heal within
# seconds.
DEFAULT_TARGET_SERVICES = [
    "inventory-service",
    "auth-service",
    "payment-service",
    "recommendation-service",
    "notification-service",
    "gateway",
]

# Stateful backing services -- only included if the caller explicitly
# opts in, since killing these has different (though still
# self-healing, via the StatefulSet from Milestone 1.J) consequences
# worth understanding deliberately, not by accident.
STATEFUL_SERVICES = ["postgres", "redis"]


def run_kubectl(args: list[str]) -> str:
    """
    Runs a kubectl command and returns its stdout, raising a clear
    error if kubectl itself isn't available or the command fails --
    rather than letting a cryptic subprocess traceback be the first
    thing the user sees.
    """
    try:
        result = subprocess.run(
            ["kubectl", *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except FileNotFoundError:
        print("ERROR: kubectl not found on PATH. Is it installed?", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: kubectl command failed: {exc.stderr.strip()}", file=sys.stderr)
        sys.exit(1)


def list_pods_for_service(service: str, namespace: str) -> list[str]:
    """
    Returns the names of all currently-running Pods backing a given
    service, by querying for Pods whose "app" label matches -- the
    exact same label every Deployment in this project stamps onto its
    Pods (see Milestone 1.J).
    """
    output = run_kubectl([
        "get", "pods",
        "-n", namespace,
        "-l", f"app={service}",
        "-o", "json",
    ])
    data = json.loads(output)
    return [item["metadata"]["name"] for item in data.get("items", [])]


def pick_target(service_filter, include_stateful: bool, namespace: str) -> tuple[str, str]:
    """
    Picks one (service, pod_name) pair to target.

    If the caller specified --service, only Pods from that service are
    considered. Otherwise, we build a pool from every candidate
    service, then pick uniformly at random across ALL currently-running
    Pods -- not one random service and then one random Pod within it,
    which would unfairly favor services that happen to have fewer
    replicas.
    """
    candidate_services = [service_filter] if service_filter else list(DEFAULT_TARGET_SERVICES)
    if include_stateful and not service_filter:
        candidate_services += STATEFUL_SERVICES

    pool: list[tuple[str, str]] = []
    for service in candidate_services:
        for pod_name in list_pods_for_service(service, namespace):
            pool.append((service, pod_name))

    if not pool:
        print("No running Pods found matching the target criteria. Is your cluster up?", file=sys.stderr)
        sys.exit(1)

    return random.choice(pool)


def kill_pod(pod_name: str, namespace: str, force: bool) -> None:
    args = ["delete", "pod", pod_name, "-n", namespace]
    if force:
        # --grace-period=0 --force skips the normal SIGTERM/drain
        # window and kills the Pod immediately -- closer to simulating
        # a hard crash (e.g. an OOM kill or node failure) than a
        # clean shutdown.
        args += ["--grace-period=0", "--force"]
    run_kubectl(args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Randomly kill a Pod to test Kubernetes self-healing.")
    parser.add_argument("--service", default=None, help="Target a specific service instead of picking randomly")
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace (default: default)")
    parser.add_argument("--include-stateful", action="store_true", help="Allow postgres/redis as possible targets")
    parser.add_argument("--force", action="store_true", help="Skip graceful termination (immediate kill)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be killed, without doing it")
    args = parser.parse_args()

    service, pod_name = pick_target(args.service, args.include_stateful, args.namespace)

    if args.dry_run:
        print(f"[DRY RUN] Would kill Pod '{pod_name}' (service: {service}) in namespace '{args.namespace}'")
        return

    print(f"Killing Pod '{pod_name}' (service: {service}) in namespace '{args.namespace}'...")
    kill_pod(pod_name, args.namespace, args.force)
    print(f"Pod '{pod_name}' deleted. Watch for its replacement with:")
    print(f"  kubectl get pods -l app={service} -w")


if __name__ == "__main__":
    main()