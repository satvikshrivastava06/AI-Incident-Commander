"""
Dependency Graph Builder
---------------------------
Consumes trace spans from the "otel-traces" Kafka topic (populated by
the OTel Collector's Kafka exporter, Milestone 1.I) and incrementally
builds a directed graph of which services call which other services --
purely by observing REAL trace data. Nothing about this system's
topology is hand-coded anywhere in this file. Every node and edge in
the resulting graph is discovered from telemetry as it arrives. (This
is "Upgrade 1 -- Dynamic Topology Discovery" from the original project
vision, arriving now as a natural consequence of the pipeline you've
already built, rather than being bolted on separately.)

Can be run standalone (`python builder.py`) to watch the graph build up
live in your terminal, or imported by backend/dependency-graph/main.py
(Step 1.33) to expose the same graph over an HTTP API.
"""

import asyncio
import logging
import os
from dataclasses import dataclass

import networkx as nx
from aiokafka import AIOKafkaConsumer
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dependency-graph-builder")

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "otel-traces")
# A DIFFERENT consumer group than telemetry-consumer's
# "telemetry-consumer-group" (Milestone 1.I). Kafka delivers a full,
# independent copy of every message to each distinct consumer group --
# this is the fan-out payoff promised back in Milestone 1.I finally
# showing up: telemetry-consumer keeps writing every span to Postgres,
# completely unaffected, while this ENTIRELY SEPARATE consumer reads
# the exact same topic for a completely different purpose. Neither
# consumer knows the other exists.
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "dependency-graph-builder-group")


@dataclass
class ParsedSpan:
    """One flattened span, extracted from a raw OTLP protobuf message --
    the same shape backend/telemetry-consumer/main.py (Milestone 1.I)
    already produces. Reused here because this genuinely IS what an
    OTLP span looks like once the protobuf parsing is done; there's no
    reason to invent a different shape for a different consumer."""
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service_name: str
    span_name: str
    duration_ms: int


def parse_trace_batch(raw_value: bytes) -> list[ParsedSpan]:
    """Decodes one Kafka message into a list of ParsedSpan records. See
    backend/telemetry-consumer/main.py for the full explanation of why
    this walks resource_spans -> scope_spans -> spans."""
    request = ExportTraceServiceRequest()
    request.ParseFromString(raw_value)

    spans = []
    for resource_spans in request.resource_spans:
        service_name = "unknown"
        for kv in resource_spans.resource.attributes:
            if kv.key == "service.name":
                service_name = kv.value.string_value

        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                span_service = service_name
                for attr in span.attributes:
                    if attr.key == "db.system":
                        db_sys = attr.value.string_value
                        if db_sys in ("postgresql", "postgres"):
                            span_service = "postgres"
                        elif db_sys == "redis":
                            span_service = "redis"
                    elif attr.key == "net.peer.name":
                        peer = attr.value.string_value
                        if peer in ("postgres", "redis"):
                            span_service = peer

                spans.append(ParsedSpan(
                    trace_id=span.trace_id.hex(),
                    span_id=span.span_id.hex(),
                    parent_span_id=span.parent_span_id.hex() if span.parent_span_id else None,
                    service_name=span_service,
                    span_name=span.name,
                    duration_ms=(span.end_time_unix_nano - span.start_time_unix_nano) // 1_000_000,
                ))
    return spans


class DependencyGraphBuilder:
    """
    Owns the graph itself, plus the bookkeeping needed to resolve
    parent -> child relationships that arrive OUT OF ORDER across
    separate Kafka messages.

    Trace spans don't arrive as one neat, top-down-processable batch --
    each service exports its own spans on its own schedule
    (BatchSpanProcessor batches every ~5s, PER SERVICE, independently).
    So it's entirely normal for a CHILD span (e.g. auth-service's
    server span) to land on the topic before the PARENT span that
    caused it (e.g. gateway's httpx client span) does. This is handled
    by keeping a registry of every span_id -> service_name seen so
    far, and retrying any edge that couldn't be resolved yet every
    time new spans arrive.
    """

    def __init__(self):
        self.graph = nx.DiGraph()
        # Maps every span_id we've ever seen to the service that
        # produced it -- this is what lets us answer "which SERVICE
        # produced the parent of this span?" even though a span only
        # ever carries its parent's span_id, never its parent's
        # service name directly.
        self._span_service_registry: dict[str, str] = {}
        # Edges we couldn't resolve yet because we hadn't seen their
        # parent span at the time -- retried after every new message.
        self._pending_edges: list[tuple[str, str, int]] = []  # (parent_span_id, child_service, duration_ms)

    def process_message(self, raw_value: bytes) -> None:
        spans = parse_trace_batch(raw_value)
        for span in spans:
            self._register_span(span)

        self._resolve_pending_edges()

    def _register_span(self, span: ParsedSpan) -> None:
        # Every service that ever emits a span becomes a node, even
        # before we know anything about its edges -- this is what lets
        # a service with no callers or callees yet (like
        # notification-service, at this point in the project) still
        # show up in the graph as an isolated node, instead of being
        # invisible just because nothing calls it.
        self.graph.add_node(span.service_name)
        self._span_service_registry[span.span_id] = span.service_name

        if not span.parent_span_id:
            # No parent at all -- this is the root span of its trace
            # (e.g. gateway's own "POST /checkout"). Nothing inside our
            # system called it, so there's no edge to draw here.
            return

        parent_service = self._span_service_registry.get(span.parent_span_id)
        if parent_service is None:
            # Haven't seen the parent span yet -- defer this edge
            # until (hopefully) a future message registers it.
            self._pending_edges.append((span.parent_span_id, span.service_name, span.duration_ms))
            return

        self._add_edge(parent_service, span.service_name, span.duration_ms)

    def _add_edge(self, parent_service: str, child_service: str, duration_ms: int) -> None:
        if parent_service == child_service:
            # A span whose parent is in the SAME service (e.g.
            # gateway's own httpx client span wrapping its own
            # eventual server-side handling of a request) isn't a
            # cross-service DEPENDENCY -- it's just internal call
            # structure within one process. We only care about edges
            # that actually cross a service boundary.
            return

        # Determine the call_type: http for normal service-to-service,
        # db/cache for infrastructure dependencies discovered via span attributes.
        call_type = "http"
        if child_service in ("postgres", "redis"):
            call_type = "db" if child_service == "postgres" else "cache"

        if self.graph.has_edge(parent_service, child_service):
            edge = self.graph[parent_service][child_service]
            edge["call_count"] += 1
            edge["total_duration_ms"] += duration_ms
        else:
            self.graph.add_edge(
                parent_service, child_service,
                call_count=1,
                total_duration_ms=duration_ms,
                call_type=call_type,
            )

    def _resolve_pending_edges(self) -> None:
        still_pending = []
        for parent_span_id, child_service, duration_ms in self._pending_edges:
            parent_service = self._span_service_registry.get(parent_span_id)
            if parent_service is None:
                still_pending.append((parent_span_id, child_service, duration_ms))
            else:
                self._add_edge(parent_service, child_service, duration_ms)
        self._pending_edges = still_pending

    def snapshot(self) -> dict:
        """
        Returns the graph's current state as plain, JSON-serializable
        Python. networkx graph objects aren't directly JSON-friendly --
        this is the translation layer main.py's /graph endpoint
        (Step 1.33) calls into.
        """
        nodes = [{"id": node} for node in self.graph.nodes()]
        edges = []
        for source, target, data in self.graph.edges(data=True):
            call_count = data["call_count"]
            total_duration_ms = data["total_duration_ms"]
            edges.append({
                "source": source,
                "target": target,
                "call_count": call_count,
                "avg_latency_ms": round(total_duration_ms / call_count, 2),
            })
        return {"nodes": nodes, "edges": edges}


async def run_consumer(builder: DependencyGraphBuilder) -> None:
    """
    Owns the Kafka consumer loop, feeding every incoming message into
    the builder.

    enable_auto_commit=True here, deliberately DIFFERENT from Milestone
    1.I's telemetry-consumer, which committed manually for at-least-
    once durability writing to Postgres. This graph is a live,
    in-memory, BEST-EFFORT view of current topology, not a durable
    record of anything. If this process restarts, rebuilding the graph
    from scratch (or from wherever the consumer group's offset happens
    to be) is completely fine -- there's no correctness requirement to
    never skip or never reprocess a span here, unlike financial
    transaction data. Match your durability guarantees to what
    actually needs them; not every consumer needs the strictest one.

    auto_offset_reset="earliest" means a brand-new consumer group
    (the first time you ever run this) reads the topic's full existing
    backlog immediately, instead of only new spans from now on --
    useful for seeing a populated graph right away during testing.
    """
    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=KAFKA_GROUP_ID,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )

    await consumer.start()
    logger.info(
        "Dependency graph builder started -> topic=%s group_id=%s bootstrap=%s",
        KAFKA_TOPIC, KAFKA_GROUP_ID, KAFKA_BOOTSTRAP_SERVERS
    )

    try:
        async for message in consumer:
            builder.process_message(message.value)
            snapshot = builder.snapshot()
            logger.info(
                "Graph updated -> nodes=%d edges=%d",
                len(snapshot["nodes"]), len(snapshot["edges"])
            )
    finally:
        await consumer.stop()


async def _main() -> None:
    builder = DependencyGraphBuilder()
    await run_consumer(builder)


if __name__ == "__main__":
    asyncio.run(_main())