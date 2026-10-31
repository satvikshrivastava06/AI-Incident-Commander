# AI Incident Commander — Full Setup & Test Runbook

Run these in order. Each phase depends on the one before it. Commands assume you're at the repo root unless a `cd` is shown.

**One real fix bundled in here:** `infra/docker-compose.yml` has carried unused `postgres`/`redis` service blocks since Milestone 1.J moved the real ones to Kubernetes — nothing has connected to the docker-compose versions since. Phase 6 replaces the file with a corrected version that removes them. (`rabbitmq` is also unused — `notification-service` has been a stub since it was written and the real notifier never touches it — left in place since removing it wasn't asked for, but worth knowing it's dead weight if you want to trim it later.)

---

## Phase 0 — One-time tool installation

```bash
# Skip anything you already have installed.
# Docker, Node.js 18+, Python 3.11+ are assumed present.

# Kubernetes CLI
brew install kubectl        # or your platform's equivalent

# A local cluster tool — pick ONE
brew install kind           # or: brew install minikube

# Helm
brew install helm

# Linkerd CLI
curl -sL https://run.linkerd.io/install | sh
export PATH=$PATH:$HOME/.linkerd2/bin
# add that export line to your shell profile (.bashrc/.zshrc) so it persists

# bcrypt, for generating the Prometheus auth hash later
pip install bcrypt
```

---

## Phase 1 — Create the cluster

```bash
# kind:
kind create cluster --name incident-commander

# — or, minikube —
minikube start
```

---

## Phase 2 — Cluster add-ons

```bash
# metrics-server (required for the payment-service HPA to work at all)
# kind:
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'
# — or, minikube —
minikube addons enable metrics-server

# Wait ~30-60s, then confirm real numbers (not an error):
kubectl top pods

# Linkerd control plane -- MUST be installed before the Helm chart
# below, since its admission webhook only injects sidecars into pods
# created AFTER it's running.
linkerd check --pre
linkerd install --crds | kubectl apply -f -
linkerd install | kubectl apply -f -
linkerd check
```

---

## Phase 3 — Build and load every container image

```bash
# 6 synthetic services
for svc in inventory-service auth-service payment-service recommendation-service notification-service gateway; do
  docker build -t $svc:latest services/$svc
done

# 4 reasoning-engine services
for svc in incident-engine dependency-graph rootcause-engine telemetry-consumer; do
  docker build -t $svc:latest backend/$svc
done

# the anomaly detector
docker build -t zscore-detector:latest ml/anomaly-detection

# Load all 11 into the cluster
IMAGES="inventory-service auth-service payment-service recommendation-service notification-service gateway incident-engine dependency-graph rootcause-engine telemetry-consumer zscore-detector"

# kind:
kind load docker-image $(for i in $IMAGES; do echo $i:latest; done) --name incident-commander

# — or, minikube —
for i in $IMAGES; do minikube image load $i:latest; done
```

---

## Phase 4 — Generate every secret

```bash
# Run each of these and save the output somewhere temporary -- you'll
# paste them into files in Phase 5 and Phase 6.

openssl rand -hex 24   # -> Postgres password
openssl rand -hex 24   # -> Redis password
openssl rand -hex 32   # -> shared API key (incident-engine / dependency-graph / rootcause-engine / dashboard / notifier)
openssl rand -hex 32   # -> OTel Collector auth token

# Prometheus basic auth -- generates BOTH forms of the SAME password.
# SAVE BOTH LINES this prints.
python3 -c "
import bcrypt, getpass
pw = getpass.getpass('Prometheus password: ')
print('plaintext (goes in infra/.env AND values-secrets.yaml):', pw)
print('bcrypt hash (goes in prometheus-web-config.yml):', bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode())
"
```

---

## Phase 5 — Configure and install the Helm chart (Kubernetes side)

```bash
cd infra/helm/incident-commander

cp values-secrets.yaml.example values-secrets.yaml
cp values-customer.yaml.example values-customer.yaml
```

Edit `values-secrets.yaml` — fill in all 5 secrets from Phase 4:
```yaml
postgresSecrets:
  password: "<postgres password from Phase 4>"
redisSecrets:
  password: "<redis password from Phase 4>"
apiSecrets:
  apiKey: "<API key from Phase 4>"
otelSecrets:
  authToken: "<OTel token from Phase 4>"
prometheusSecrets:
  password: "<Prometheus PLAINTEXT password from Phase 4>"
```

Edit `values-customer.yaml` — set a real identifier:
```yaml
customer:
  id: "your-name-dev"
  version: "2026-09-26"
```

Install:
```bash
helm upgrade --install incident-commander . \
  -f values.yaml -f values-secrets.yaml -f values-customer.yaml

# Watch until everything is Running and every pod shows 2/2
# (app container + linkerd-proxy sidecar)
kubectl get pods -w
```
Press Ctrl+C once all 11 Deployments + the Postgres StatefulSet are ready.

---

## Phase 6 — Configure and start the docker-compose stack

```bash
cd ../../../infra   # back to infra/ from the Helm chart directory
```

**File name:** `infra/docker-compose.yml` (corrected — removes the orphaned `postgres`/`redis` blocks)

```yaml
services:
  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    container_name: rabbitmq
    ports:
      - "5672:5672"
      - "15672:15672"
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 10s
      timeout: 10s
      retries: 5
    networks:
      - incident-net

  prometheus:
    image: prom/prometheus:v3.8.1
    container_name: prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--web.config.file=/etc/prometheus/web-config.yml"
    volumes:
      - ../observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ../observability/prometheus-web-config.yml:/etc/prometheus/web-config.yml:ro
    ports:
      - "9090:9090"
    networks:
      - incident-net

  grafana:
    image: grafana/grafana:13.1.0
    container_name: grafana
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer
      PROMETHEUS_BASIC_AUTH_PASSWORD: ${PROMETHEUS_BASIC_AUTH_PASSWORD}
    volumes:
      - ../observability/grafana/provisioning:/etc/grafana/provisioning:ro
      - ../observability/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    depends_on:
      - prometheus
      - tempo
      - loki
    networks:
      - incident-net

  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.156.0
    container_name: otel-collector
    command: ["--config=/etc/otel-collector-config.yaml"]
    environment:
      OTEL_AUTH_TOKEN: ${OTEL_AUTH_TOKEN}
    volumes:
      - ../observability/otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro
    ports:
      - "4317:4317"
      - "4318:4318"
    depends_on:
      tempo:
        condition: service_started
      kafka:
        condition: service_healthy
    networks:
      - incident-net

  tempo:
    image: grafana/tempo:2.9.0
    container_name: tempo
    command: ["-config.file=/etc/tempo.yaml"]
    volumes:
      - ../observability/tempo-config.yaml:/etc/tempo.yaml:ro
      - tempo_data:/var/tempo
    ports:
      - "3200:3200"
    networks:
      - incident-net

  loki:
    image: grafana/loki:3.7.0
    container_name: loki
    command: ["-config.file=/etc/loki/loki-config.yaml"]
    volumes:
      - ../observability/loki-config.yaml:/etc/loki/loki-config.yaml:ro
      - loki_data:/loki
    ports:
      - "3100:3100"
    networks:
      - incident-net

  promtail:
    image: grafana/promtail:3.7.0
    container_name: promtail
    command: ["-config.file=/etc/promtail/promtail-config.yaml"]
    volumes:
      - ../observability/promtail-config.yaml:/etc/promtail/promtail-config.yaml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    depends_on:
      - loki
    networks:
      - incident-net

  kafka:
    image: apache/kafka:4.3.1
    container_name: kafka
    hostname: kafka
    ports:
      - "9092:9092"
      - "9094:9094"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://kafka:19092,CONTROLLER://kafka:9093,PLAINTEXT_HOST://0.0.0.0:9092,PLAINTEXT_K8S://0.0.0.0:9094
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:19092,PLAINTEXT_HOST://localhost:9092,PLAINTEXT_K8S://host.docker.internal:9094
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT,PLAINTEXT_K8S:PLAINTEXT
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0
      CLUSTER_ID: MkU3OEVBNTcwNTJENDM2Qk
    volumes:
      - kafka_data:/var/lib/kafka/data
    healthcheck:
      test: ["CMD-SHELL", "/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092"]
      interval: 10s
      timeout: 10s
      retries: 10
      start_period: 20s
    networks:
      - incident-net

networks:
  incident-net:
    driver: bridge

volumes:
  grafana_data:
  tempo_data:
  loki_data:
  kafka_data:
```

Configure secrets and Prometheus auth:
```bash
cp .env.example .env
```
Edit `infra/.env`:
```
PROMETHEUS_BASIC_AUTH_PASSWORD=<Prometheus PLAINTEXT password from Phase 4>
OTEL_AUTH_TOKEN=<OTel token from Phase 4 -- SAME value as values-secrets.yaml>
```

```bash
cd ../observability
cp prometheus-web-config.yml.example prometheus-web-config.yml
```
Edit `observability/prometheus-web-config.yml` — paste the bcrypt **hash** from Phase 4:
```yaml
basic_auth_users:
  admin: "<bcrypt hash from Phase 4>"
```

Start the stack:
```bash
cd ../infra
docker compose up -d --build

# Confirm 8 containers healthy
docker compose ps
```

---

## Phase 7 — Database migration (safety net)

Only matters if you have an `incidents` table left over from earlier testing that predates the accuracy-feedback-loop update. Harmless to run either way:
```bash
kubectl port-forward svc/postgres 5432:5432 &
docker run --rm -it --network host postgres:16-alpine psql \
  -h localhost -U incident_admin -d incident_commander \
  -c "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS confirmed_root_cause VARCHAR(100);"
# (enter the Postgres password from Phase 4 when prompted)
```

---

## Phase 8 — Configure and run the notifier (standalone — not yet containerized)

```bash
cd ../backend/notifier
cp .env.example .env
```
Edit `backend/notifier/.env`:
```
API_KEY=<API key from Phase 4>
NOTIFICATION_CHANNEL=console
```
(Switch to `slack`/`pagerduty`/`webhook` and fill in the matching URL/key once you've created those credentials in your own account — see the platform-decisions discussion for how.)

```bash
pip install -r requirements.txt
python main.py --test        # confirm delivery works before the real loop
```

---

## Phase 9 — Configure and run the dashboard

```bash
cd ../../apps/incident-dashboard
cp .env.local.example .env.local
```
Edit `.env.local`:
```
VITE_API_KEY=<API key from Phase 4>
```

```bash
npm install
npm run dev
```
Open `http://localhost:5174`.

---

## Phase 10 — Port-forwards for local access

Keep these running in dedicated terminals for the rest of this session:
```bash
kubectl port-forward svc/gateway 8005:8005
kubectl port-forward svc/incident-engine 8007:8007
kubectl port-forward svc/dependency-graph 8006:8006
kubectl port-forward svc/rootcause-engine 8008:8008
```

---

## Phase 11 — Smoke test

```bash
# Health checks -- no auth required on any of these
curl http://localhost:8005/health
curl http://localhost:8007/health
curl http://localhost:8006/health
curl http://localhost:8008/health

# Auth actually enforced (expect 401)
curl -i http://localhost:8007/incidents

# Auth working (expect 200)
curl -i http://localhost:8007/incidents -H "X-API-Key: <API key from Phase 4>"

# Generate real traffic
cd ../../chaos
python traffic_generator.py --gateway-url http://localhost:8005 --rate 3 --duration 60

# After ~60s, confirm topology was discovered from real trace data
curl http://localhost:8006/graph -H "X-API-Key: <API key>" | python -m json.tool
```
Expect to see `gateway → auth-service`, `gateway → payment-service`, `gateway → inventory-service`, `gateway → recommendation-service`, plus `payment-service → postgres` and `payment-service → redis` as real discovered edges.

```bash
# Confirm Grafana + Prometheus auth chain
open http://localhost:3000   # Services Overview dashboard should render live data
```

---

## Phase 12 — Full incident lifecycle test

```bash
# Start the anomaly detector (this run happens standalone for the
# test; it also runs continuously inside the cluster via the Helm
# chart's `workers` list)
kubectl logs -f deploy/zscore-detector &

# Force a real, sustained anomaly
cd ../chaos
python inject_latency.py --service payment-service --delay-ms 2000 --duration 90

# In another terminal, run the notifier's real polling loop
cd ../backend/notifier
python main.py --poll-interval 10
```
Within a couple of poll cycles you should see: an incident appear on the dashboard, `payment-service` turn red on the Service Map, and a real alert land wherever `NOTIFICATION_CHANNEL` points.

```bash
# Confirm the prediction was persisted
curl http://localhost:8007/incidents?status=open -H "X-API-Key: <key>"
# copy the incident id

# Resolve it, confirming the real cause
curl -X POST http://localhost:8007/incidents/<id>/resolve \
  -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"confirmed_root_cause": "redis"}'

# Check the measured accuracy number
curl http://localhost:8007/accuracy -H "X-API-Key: <key>" | python -m json.tool
```

---

## Phase 13 — Teardown (when you're done testing)

```bash
# Stop port-forwards and local processes: Ctrl+C in each terminal

docker compose down          # add -v to also wipe Kafka/Grafana/Tempo/Loki volumes
helm uninstall incident-commander
kind delete cluster --name incident-commander   # or: minikube delete
```
