# AI Incident Commander — Master Developer Roadmap

*A single, cohesive build plan that merges your original project outline with all 10 "upgrade" ideas, organized into beginner-friendly micro-steps.*

---

## 0. How I integrated your document

Your file actually contained three layers that were written at different times and never merged:

1. **The original MVP plan** (sections 1–13: telemetry → anomalies → root cause → simulation → deployment).
2. **A separate 5-phase "learning roadmap"** (Python → distributed systems → containers → Kubernetes → observability) meant to be studied *before* building.
3. **10 "upgrades" + a "Level 1–10" vision** pasted at the end, which are really just deeper versions of the same 6 engines (dependency graph, root cause, simulation, forecasting, copilot, MLOps).

Since you said you want to **learn while building**, I dropped the idea of a separate up-front "study phase." Instead, every micro-step below teaches you exactly the concept you need *at the moment you need it* — the Python/Docker/K8s/observability theory from your Phase 1–5 list is folded directly into the "Learning Objective" column of the relevant build steps. Nothing from your file was discarded; it was re-sequenced.

Each of your 10 upgrades is not a bonus round tacked on at the end — it's woven into the stage where it naturally belongs:

| Upgrade / Level | Where it lives now |
|---|---|
| Upgrade 1 — Dynamic Topology Discovery | Stage 1 (the graph is built from traces from day one, never hand-coded) |
| Upgrade 4 — Deployment-aware detection (basic) | Stage 1 (we log deployments from the start) |
| Upgrade 4 (full ML correlation) | Stage 3 |
| Upgrade 5 — Blast radius via graph algorithms | Stage 2 |
| Upgrade 3 — Counterfactual simulation | Stage 2 (basic) → Stage 4 (full economic version) |
| Upgrade 2 — Causal graphs (DoWhy/EconML) | Stage 3 |
| Upgrade 6 — Incident knowledge graph | Stage 3 |
| Upgrade 7 — Temporal GNNs | Stage 4 |
| Upgrade 8 — SLO-aware reasoning | Stage 4 |
| Upgrade 9 — Autonomous mitigation recommendations | Stage 4 |
| Upgrade 10 — Infrastructure Time Machine | Stage 4 |
| Level 5/10 — Economic & multi-objective optimization | Stage 4 |
| Level 9 — Self-improving platform | Stage 4 |

**Your own file's staging strategy (Stage 1–4, to avoid never finishing) is kept exactly as you wrote it** — I just filled in the micro-steps underneath it.

---

## 1. The cohesive one-line vision

> An AI-powered infrastructure reasoning platform that builds a live digital twin of a microservice system from telemetry, explains incidents causally (not just by correlation), simulates "what-if" failures and interventions, forecasts risk against SLOs, and recommends — and eventually learns from — mitigation actions.

Everything you build is one of six engines sitting behind one dashboard:

```
Application Layer
├── Incident Dashboard
├── Digital Twin / Simulation UI
└── AI Copilot

Backend Layer
├── Incident Engine
├── Dependency-Graph / Root-Cause Engine
├── Simulation Engine
└── Forecasting Engine

Data Layer
├── Metrics Store (Prometheus)
├── Logs Store (Loki)
├── Traces Store (Tempo)
└── Dependency Graph (Neo4j)

Infrastructure Layer
├── Kubernetes / Docker / Helm / Terraform
└── Kafka (telemetry backbone)
```

---

## 2. Tech stack — strictly what's in your file

| Layer | Technology (from your document) |
|---|---|
| Frontend | React |
| Backend | FastAPI |
| ML | PyTorch, XGBoost, LightGBM, Prophet, Temporal Fusion Transformer, GraphSAGE / GAT, Isolation Forest, One-Class SVM, LSTM Autoencoders, DoWhy, EconML |
| Data | PostgreSQL, Redis, Neo4j, NetworkX, object storage |
| Messaging | Kafka, RabbitMQ |
| Observability | OpenTelemetry, Prometheus, Grafana, Loki, Tempo |
| MLOps | MLflow, DVC |
| Infra | Docker, Kubernetes, Helm, Terraform, CI/CD |
| Cloud | GCP / AWS / Azure (your choice) |
| Copilot | RAG + a vector database (your file doesn't name a specific product — pick one when we reach that step) |

**One important distinction your file blurs:** RabbitMQ and Kafka are *not* interchangeable here. RabbitMQ is one of the fake backing services **inside** the synthetic e-commerce system you're monitoring (like Postgres and Redis — something your platform observes). Kafka is the **telemetry backbone your platform itself uses** to move metrics/traces between your own services. Keep that mental separation from the start.

---

## 3. Repo layout you'll build toward

```
ai-incident-commander/
├── services/                  # the FAKE e-commerce system you monitor
│   ├── gateway/
│   ├── auth-service/
│   ├── payment-service/
│   ├── inventory-service/
│   ├── recommendation-service/
│   └── notification-service/
├── apps/
│   ├── synthetic-shop-frontend/   # the fake shop's UI (traffic source)
│   └── incident-dashboard/        # YOUR product's UI
├── backend/                   # YOUR platform's own services
│   ├── dependency-graph/
│   ├── incident-engine/
│   ├── rootcause-engine/
│   ├── simulation-engine/
│   ├── forecasting-engine/
│   ├── reliability-engine/
│   ├── knowledge-graph/
│   └── copilot/
├── ml/
│   ├── anomaly-detection/
│   ├── rca-models/
│   ├── forecasting/
│   ├── causal/
│   ├── gnn/
│   ├── copilot/
│   └── mlops/
├── chaos/                      # fault injection + traffic generation
├── observability/               # otel, prometheus, grafana, loki config
└── infra/                       # docker-compose, k8s, helm, terraform
```

---

## 4. How to read the roadmap

- Every step lists **exactly 1–2 files** to create or edit. Don't move to the next step until the current one runs.
- **Files** = what you touch. **Build** = what it does. **Learning Objective** = the concept this step is teaching you, independent of this specific project.
- Stages follow your file's own staging strategy: **Stage 1 (2–3 months)**, **Stage 2 (2 months)**, **Stage 3 (2 months)**, **Stage 4 (optional, stretch)**.
- Steps inside a stage are numbered sequentially (1.1, 1.2, …) so you always know where you are.

---

## STAGE 1 — Foundations: Telemetry, Dependency Graph, Basic Root Cause (2–3 months)

### Milestone 1.A — Project scaffolding

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.1 | `README.md`, `.gitignore` | Init git repo; write a one-paragraph project description | Version control basics, why repo hygiene matters from commit #1 |
| 1.2 | Empty folders per §3 | Create the skeleton directory structure, commit it | How real projects organize a monorepo *before* code exists |

### Milestone 1.B — First synthetic service

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.3 | `services/inventory-service/main.py` | FastAPI app with `GET /health` and `GET /inventory/{item_id}` returning mock stock data | FastAPI routing, path parameters, JSON responses |
| 1.4 | `services/inventory-service/Dockerfile`, `requirements.txt` | Containerize and run it with `docker build` / `docker run` | Dockerfile anatomy (base image, COPY, CMD), image layers |

### Milestone 1.C — The rest of the synthetic e-commerce system

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.5 | `services/auth-service/main.py` + Dockerfile | `POST /login` returns a mock token | Request bodies with Pydantic models |
| 1.6 | `services/payment-service/main.py` + Dockerfile | `POST /charge` with an artificial `asyncio.sleep()` to simulate real latency | Why you deliberately inject latency into a demo system — it's what makes monitoring *meaningful* |
| 1.7 | `services/recommendation-service/main.py` + Dockerfile | `GET /recommendations/{user_id}` | Reinforcing the FastAPI pattern until it's muscle memory |
| 1.8 | `services/notification-service/main.py` + Dockerfile | `POST /notify`, stub-publishes to RabbitMQ | Async message publishing pattern |
| 1.9 | `services/gateway/main.py` + Dockerfile | Calls auth → payment → inventory → recommendation using `httpx` | Service-to-service HTTP calls, the "fan-out" pattern, async HTTP clients |
| 1.10 | `apps/synthetic-shop-frontend/src/App.jsx`, `package.json` | Minimal React app with one "Checkout" button that calls the gateway | React basics: components, `fetch`, `useState` |

### Milestone 1.D — Backing services & networking

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.11 | `infra/docker-compose.yml` | Wire all 6 services + Postgres + Redis + RabbitMQ onto one network | docker-compose service discovery via container names, env vars |
| 1.12 | `services/payment-service/main.py` (edit) | Replace stubs with real Postgres (`asyncpg`) and Redis (`redis-py`) calls | Connecting to databases from Python, connection pooling |

### Milestone 1.E — Synthetic traffic

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.13 | `chaos/traffic_generator.py` | `asyncio` script hitting the checkout flow N times/sec with randomized delays | `asyncio` concurrency, generating realistic load |

### Milestone 1.F — Instrumentation (OpenTelemetry)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.14 | `services/gateway/main.py`, `services/payment-service/main.py` (edit) | Add OpenTelemetry auto-instrumentation (traces + metrics middleware) | What a "span" is; how tracing context propagates across service calls |
| 1.15 | Same edit repeated across the 4 remaining services | Instrument every service the same way | Recognizing and applying boilerplate patterns quickly — a core senior-engineer skill |

### Milestone 1.G — Metrics & dashboards

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.16 | `observability/prometheus.yml` | Configure scrape targets for each service's `/metrics` | Prometheus's pull-based scraping model |
| 1.17 | `infra/docker-compose.yml` (edit) | Add Prometheus + Grafana containers | Wiring a monitoring stack into an existing compose file |
| 1.18 | `observability/grafana/dashboards/services-overview.json` | First dashboard: CPU / latency / error-rate panels | Basic PromQL, reading time-series panels |

### Milestone 1.H — Traces & logs

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.19 | `observability/otel-collector-config.yaml` | Configure the OTel Collector to export traces to Tempo | The agent → collector → backend pipeline pattern |
| 1.20 | `infra/docker-compose.yml` (edit) | Add Tempo + Loki; point service logs at Loki | Metrics, logs, and traces as three complementary "pillars" |

### Milestone 1.I — Kafka telemetry backbone

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.21 | `infra/docker-compose.yml` (edit) | Add Kafka + Zookeeper | Publish/subscribe messaging fundamentals |
| 1.22 | `observability/otel-collector-config.yaml` (edit) | Add a Kafka exporter so telemetry also flows onto a topic | Fan-out architecture; decoupling producers from consumers |
| 1.23 | `backend/telemetry-consumer/main.py` | Consume the Kafka topic, write events into Postgres | Consumer groups, "at-least-once" processing |

### Milestone 1.J — Migrate to Kubernetes

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.24 | `infra/k8s/inventory-service-deployment.yaml` | First Deployment + Service manifest, applied to `kind`/`minikube` | Deployment vs. Pod vs. Service objects, the `kubectl apply` workflow |
| 1.25 | One manifest per remaining service (batch as one repeatable step) | Migrate the rest of the stack | Reinforcing manifest authoring; noticing the repeating template |
| 1.26 | `infra/k8s/postgres-statefulset.yaml` | StatefulSet + PersistentVolumeClaim for Postgres | Why stateful workloads need StatefulSets, not Deployments |
| 1.27 | `infra/helm/incident-commander/Chart.yaml`, `values.yaml` | Wrap your manifests into a first Helm chart | Templating repeated YAML; parameterized deployments |

### Milestone 1.K — Resilience primitives

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.28 | `infra/k8s/payment-service-deployment.yaml` (edit), `infra/k8s/payment-service-hpa.yaml` | Add readiness/liveness probes + a Horizontal Pod Autoscaler | Health checks, autoscaling triggers |

### Milestone 1.L — Fault injection tooling

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.29 | `chaos/kill_pod.py` | Script wrapping `kubectl delete pod` on a random target pod | Simulating crashes; observing Kubernetes self-healing |
| 1.30 | `chaos/inject_latency.py` | Use Linux `tc` inside a target container to add artificial delay | How latency propagates through a call chain |
| 1.31 | `chaos/stress_cpu.py` | Script that burns CPU inside a target pod for N seconds | Resource-exhaustion failure modes |

### Milestone 1.M — Dynamic Dependency Graph Discovery (Upgrade 1)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.32 | `backend/dependency-graph/builder.py` | Consume trace spans from Kafka, extract parent→child calls, build a `networkx.DiGraph` | Graph data structures; parsing trace-span parent/child relationships |
| 1.33 | `backend/dependency-graph/main.py` | `GET /graph` returns nodes + edge weights (call frequency, latency) as JSON | Exposing an in-memory data structure through an API; edge-weighted graphs |

### Milestone 1.N — Incident Engine skeleton

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.34 | `backend/incident-engine/models.py` | SQLAlchemy models: `Incident`, `Deployment` | ORM basics, relational schema design |
| 1.35 | `backend/incident-engine/main.py` | `POST /incidents`, `GET /incidents` | REST CRUD pattern with Pydantic schemas |
| 1.36 | `chaos/log_deployment.py` | Small script writing a fake deployment event (service, version, timestamp) whenever you "redeploy" | Groundwork for Upgrade 4 — why deployment metadata matters for root-cause analysis later |

### Milestone 1.O — Anomaly Detection v1

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.37 | `ml/anomaly-detection/zscore_detector.py` | Pull recent metric windows from Prometheus, compute rolling z-score, flag anomalies | Descriptive statistics (mean/std), sliding-window computation |
| 1.38 | `backend/incident-engine/main.py` (edit) | When the detector flags something, `POST` a new Incident automatically | Connecting a statistical component to a backend service — the detect→act loop |

### Milestone 1.P — Root Cause Engine v1 (rule-based)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.39 | `backend/rootcause-engine/rules.py` | If/else rules (e.g. "payment latency↑ + redis CPU↑ → 0.7 probability redis") using graph proximity | Rule-based reasoning; why a simple baseline beats no baseline |
| 1.40 | `backend/rootcause-engine/main.py` | `POST /rootcause/{incident_id}` returns ranked probable causes | Designing a clean API contract for a reasoning engine |

### Milestone 1.Q — Dashboard v1

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.41 | `apps/incident-dashboard/src/App.jsx` | Incident list fetched from the incident-engine | Fetching + rendering lists in React |
| 1.42 | `apps/incident-dashboard/src/ServiceMap.jsx` | Render the dependency graph in plain SVG; color nodes red if implicated | SVG fundamentals; mapping data to visual attributes |

### Milestone 1.R — Stage 1 demo

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 1.43 | *(no new files)* | Start the stack, run `traffic_generator.py`, run `kill_pod.py` on redis, watch the dashboard surface an anomaly → rule-based root cause | End-to-end systems thinking; debugging across service boundaries — this is where Stage 1 clicks together |

---

## STAGE 2 — Digital Twin, Failure Simulation, Blast Radius (2 months)

### Milestone 2.A — Persist the graph as a real digital twin

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 2.1 | `infra/docker-compose.yml` (or `infra/k8s/neo4j-deployment.yaml`) | Add Neo4j | Graph databases vs. in-memory graphs — why persistence matters |
| 2.2 | `backend/dependency-graph/neo4j_writer.py` | Periodically sync the NetworkX graph into Neo4j via Cypher | Cypher basics; `MERGE` for idempotent writes |
| 2.3 | `backend/dependency-graph/main.py` (edit) | Swap `/graph` to read from Neo4j instead of memory | Querying a graph database from application code |

### Milestone 2.B — Simulation Engine v1 (static propagation)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 2.4 | `backend/simulation-engine/main.py` | `POST /simulate/fail/{service}` does BFS/DFS from the failed node over dependency edges | Graph traversal algorithms; simulating cascading failure |
| 2.5 | `backend/simulation-engine/models.py` | Pydantic models for simulation input/output (affected services, estimated severity) | Designing structured output schemas for a reasoning engine |

### Milestone 2.C — Blast Radius Engine (Upgrade 5)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 2.6 | `backend/simulation-engine/blast_radius.py` | Compute PageRank, betweenness centrality, and shortest-path distance for a failed node | Graph centrality algorithms and what they mean operationally |
| 2.7 | `backend/simulation-engine/main.py` (edit) | `GET /blast-radius/{service}` combines traversal + centrality into a ranked impact report | Composing multiple algorithms into one decision output |

### Milestone 2.D — Simulation UI

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 2.8 | `apps/incident-dashboard/src/SimulationPanel.jsx` | Pick a service, click "Simulate Failure," highlight affected nodes on the map | Connecting frontend interactions to backend compute endpoints |

### Milestone 2.E — Counterfactual Simulation v1 (Upgrade 3, basic)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 2.9 | `backend/simulation-engine/counterfactual.py` | Accept parameters (`redis_replicas`, `payment_replicas`) and apply a heuristic formula estimating latency/cost delta | Parameterized "what-if" modeling; prediction vs. simulation |
| 2.10 | `apps/incident-dashboard/src/WhatIfPanel.jsx` | Inputs for replica counts, shows predicted latency/cost/availability delta | Controlled inputs in React; interactive "what-if" tools |

### Milestone 2.F — Validate the simulator

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 2.11 | `chaos/validate_simulation.py` | Run a real fault injection, record actual impact, compare against the `/blast-radius` prediction | Model validation methodology — predicted vs. actual |

### Milestone 2.G — Stage 2 demo

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 2.12 | *(no new files)* | Simulate a failure in the UI, then actually trigger it, then compare | Closing the loop between simulation and reality |

---

## STAGE 3 — Causal Reasoning, Forecasting, Incident Copilot (2 months)

### Milestone 3.A — Root Cause Engine v2 (ML)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 3.1 | `ml/rca-models/features.py` | Build a feature vector per incident: CPU, memory, latency, errors, dependency distance, time-since-deployment | Feature engineering; joining telemetry + graph + deployment data |
| 3.2 | `chaos/label_incident.py` | When you deliberately run a fault-injection script, auto-tag the resulting Incident with ground-truth root cause | How supervised datasets get created in practice |
| 3.3 | `ml/rca-models/train_xgboost.py` | Train an XGBoost classifier on labeled incidents | Supervised classification, train/test split, precision/recall |
| 3.4 | `ml/rca-models/train_lightgbm.py` | Train LightGBM, compare | Comparing gradient-boosting implementations; overfitting on small data |
| 3.5 | `backend/rootcause-engine/main.py` (edit) | `POST /rootcause/{incident_id}/ml` alongside the existing rule-based endpoint | Serving a model inside an existing API; versioning strategies side by side |

### Milestone 3.B — Causal Graph Layer (Upgrade 2)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 3.6 | `ml/causal/scm.py` | Define a Structural Causal Model (Redis → Cache → DB → Payment) with DoWhy | Causal DAGs; correlation vs. causation |
| 3.7 | `ml/causal/query_counterfactual.py` | Run a DoWhy/EconML counterfactual query against real incident data | Counterfactual estimation techniques |

### Milestone 3.C — Deployment-Aware Detection (Upgrade 4, full)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 3.8 | `backend/incident-engine/deployment_correlator.py` | Compute time-delta between each incident and the nearest prior deployment per implicated service; boost that service's probability | Temporal event correlation, windowed joins |

### Milestone 3.D — Forecasting Engine

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 3.9 | `ml/forecasting/prophet_forecast.py` | Train Prophet on historical CPU/memory/latency, forecast 15 minutes ahead | Trend/seasonality decomposition; forecasting basics |
| 3.10 | `ml/forecasting/xgboost_forecast.py` | Reframe forecasting as regression with lag features | Feature-based time-series forecasting |
| 3.11 | `ml/forecasting/tft_forecast.py` | Train a Temporal Fusion Transformer for multi-horizon forecasting | Introductory attention-based sequence models |
| 3.12 | `backend/forecasting-engine/main.py` | Serve the best-performing model via FastAPI | Model comparison → productionization decisions |

### Milestone 3.E — Incident Knowledge Graph (Upgrade 6)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 3.13 | `backend/incident-engine/models.py` (edit) | Add `symptoms`, `resolution` fields | Iterative schema evolution / migrations |
| 3.14 | `backend/knowledge-graph/sync.py` | Push resolved incidents into Neo4j as `(:Incident)-[:CAUSED_BY]->(:Cause)` | Modeling domain knowledge as a graph |

### Milestone 3.F — Vector search & AI Copilot

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 3.15 | `ml/copilot/embed_incidents.py` | Generate embeddings for incident descriptions, store in a vector database | What embeddings are; semantic similarity search |
| 3.16 | `backend/knowledge-graph/similar_incidents.py` | `GET /incidents/{id}/similar` returns nearest neighbors | Nearest-neighbor retrieval |
| 3.17 | `backend/copilot/rag_pipeline.py` | Retrieve similar incidents + current telemetry, assemble a prompt, generate an explanation with confidence + evidence | Retrieval-augmented generation, end to end |
| 3.18 | `backend/copilot/main.py` | `POST /copilot/ask` | Wrapping an LLM pipeline behind a clean API |
| 3.19 | `apps/incident-dashboard/src/CopilotPanel.jsx` | Chat-style panel calling `/copilot/ask` | Chat UI patterns, async loading states |

### Milestone 3.G — MLOps baseline

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 3.20 | `ml/rca-models/train_xgboost.py` (edit) | Wrap training with MLflow experiment tracking | Experiment tracking, reproducibility |
| 3.21 | `ml/mlops/registry_promote.py` | Promote a model from MLflow "staging" to "production," which the serving endpoint reads | Model registry pattern; decoupling training from serving |

### Milestone 3.H — Stage 3 demo

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 3.22 | *(no new files)* | Fault occurs → ML root cause → causal counterfactual check → forecast flags SLO risk → ask the copilot "why did checkout fail?" | Orchestrating a multi-model pipeline into one coherent, user-facing answer |

---

## STAGE 4 — Optional Stretch: Economics, Autonomy, Self-Learning

*Only start this once Stages 1–3 work end-to-end. This is what pushes the project from "excellent portfolio piece" to "resembles an internal platform team's tooling."*

### Milestone 4.A — GNN-based Root Cause v3

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.1 | `ml/gnn/graph_dataset.py` | Convert the Neo4j graph + node features into PyTorch tensors | Representing graphs as tensors for deep learning |
| 4.2 | `ml/gnn/train_graphsage.py` | Train a GraphSAGE model to predict root-cause probability per node | Message-passing / graph neural network fundamentals |
| 4.3 | `ml/gnn/train_gat.py` | Train a Graph Attention Network, compare | Attention over graph neighborhoods |

### Milestone 4.B — Temporal Graph Networks (Upgrade 7)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.4 | `ml/gnn/temporal_dataset.py` | Build time-windowed graph snapshots | Representing time as a sequence of graph states |
| 4.5 | `ml/gnn/train_temporal_gnn.py` | Extend training to consume snapshot sequences, predict "which service fails next" | Combining temporal + graph structure; predictive failure propagation |

### Milestone 4.C — SLO-Aware Reasoning (Upgrade 8)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.6 | `backend/reliability-engine/slo.py` | Define SLOs (99.95% availability, 250ms p95); compute current error-budget burn rate | SRE error-budget math |

### Milestone 4.D — Economic Optimization (Level 5)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.7 | `backend/reliability-engine/optimizer.py` | Given candidate actions with (cost, availability_gain), compute a Pareto-efficient recommendation | Multi-objective optimization; the Pareto frontier |

### Milestone 4.E — Autonomous Mitigation Recommendations (Upgrade 9)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.8 | `backend/rootcause-engine/mitigations.py` | Rank actions (scale redis, rollback, cache warming) by confidence from historical outcomes | Recommendation ranking systems |
| 4.9 | `apps/incident-dashboard/src/MitigationPanel.jsx` | Show ranked recommendations with an Approve/Reject button (human stays in the loop) | Human-in-the-loop UX for AI recommendations |

### Milestone 4.F — Self-Improving Feedback Loop (Level 9)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.10 | `backend/incident-engine/models.py` (edit), `ml/rca-models/update_confidence.py` | Add `outcome_quality`; recompute action confidence from logged outcomes | Continual/online learning basics |

### Milestone 4.G — Multi-Objective Decision Engine (Level 10)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.11 | `backend/reliability-engine/optimizer.py` (edit) | Weigh cost, availability, latency, and a carbon-proxy metric together | Weighted multi-criteria decision making |

### Milestone 4.H — Infrastructure Time Machine (Upgrade 10)

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.12 | `backend/dependency-graph/snapshot.py` | Periodically snapshot graph + deployments + metrics-summary to object storage, timestamped | Event sourcing / temporal snapshotting |
| 4.13 | `backend/dependency-graph/replay.py` | `GET /timeline?at=<timestamp>` reconstructs topology/state at a past moment | Reconstructing historical state from immutable snapshots |

### Milestone 4.I — Full MLOps maturity

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.14 | `ml/mlops/dvc_pipeline.yaml` | Version training datasets with DVC | Data versioning, reproducible ML pipelines |
| 4.15 | `ml/mlops/drift_monitor.py` | Compare live feature distributions vs. training distribution, flag drift | Model drift detection |

### Milestone 4.J — Production deployment

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.16 | `infra/terraform/main.tf` | Define a small managed Kubernetes cluster on your chosen cloud (GCP/AWS/Azure) | Infrastructure-as-code fundamentals |
| 4.17 | CI/CD pipeline config file (e.g. `.ci/pipeline.yaml`) | Build/test/deploy pipeline triggered on push | CI/CD automation concepts |

### Milestone 4.K — Final polish

| Step | Files | Build | Learning Objective |
|---|---|---|---|
| 4.18 | `README.md` (edit) | Architecture diagram, setup instructions, resume bullet | Technical writing — documenting a system for others and for interviewers |

---

## 5. Suggested pacing

| Stage | Duration (from your file) | Steps |
|---|---|---|
| Stage 1 — Foundations | 2–3 months | 1.1 – 1.43 |
| Stage 2 — Digital Twin | 2 months | 2.1 – 2.12 |
| Stage 3 — Causal Reasoning & Copilot | 2 months | 3.1 – 3.22 |
| Stage 4 — Optional Stretch | Open-ended | 4.1 – 4.18 |

**Rule of thumb:** don't start a step until the previous one runs and you could explain *why* it works to someone else. If a step feels too big when you sit down to do it, it's a sign to split it further — that's normal and expected for a beginner working through a project this ambitious.

Whenever you're ready, tell me which step you're on (e.g. "starting 1.3") and I'll walk you through writing that specific file, line by line, explaining the concepts as we go.
