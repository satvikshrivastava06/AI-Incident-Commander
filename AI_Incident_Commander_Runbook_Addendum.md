# Runbook Addendum — Read This First

**This file overrides `AI_Incident_Commander_Setup_Runbook.md` wherever the two disagree.** It was written after an agent's launch analysis of the actual machine (Node 24, Python 3.13.9, **no Docker, kubectl, kind, or Helm**) turned up missing files and several problems in the original runbook.

**What I could not do:** run Docker or Kubernetes myself. The checkpoints in Section 3 exist to catch anything I got wrong. If a checkpoint fails, stop there and send the exact output. Don't push on to the next stage.

---

## 0. Unpack the missing files (do this first)

Unzip `incident-commander-missing-files.zip` **at the repo root**. Answer "yes" to overwrite `chaos/requirements.txt`; that is intentional (see Correction C).

| File | Why you need it |
|---|---|
| `services/auth-service/Dockerfile`, `services/payment-service/Dockerfile` | Never pasted. Without them, 2 of the 6 images cannot be built. |
| `backend/{incident-engine,dependency-graph,rootcause-engine,telemetry-consumer}/Dockerfile` | Never pasted. The Helm chart references these images. |
| `ml/anomaly-detection/Dockerfile` | Never pasted. Builds the `zscore-detector` image. |
| `infra/.env.example` | Never pasted. Holds the docker-compose secrets. |
| `observability/prometheus-web-config.yml.example` | Never pasted. Prometheus auth cannot be set up without it. |
| `infra/helm/incident-commander/values-customer.yaml.example` | Never pasted. |
| `infra/kind-config.yaml` | **New.** Fixes Correction A. |
| `chaos/requirements.txt` | **Updated.** Fixes Correction C. |
| `scripts/preflight.sh` | **New.** Checks that every file exists and is at its final version. |

Then run:
```bash
bash scripts/preflight.sh
```
Every `FAIL` line is a missing or stale file. Fix them all before installing anything. The most likely culprits are the files I only described as small edits (the `OTEL_AUTH_TOKEN` / `deployment.id` lines in the 5 smaller services, and the Prometheus auth in `zscore_detector.py`). Those are easy to miss, and the script checks for them.

---

## 1. Install the tools (the real blocker)

Nothing in the runbook works until Docker is running. Docker Desktop has a GUI installer and will ask for a restart, so you do this part yourself.

**Windows** (run the runbook in **Git Bash**, not PowerShell or CMD, because the commands use bash syntax):
```powershell
winget install -e --id Git.Git
winget install -e --id Docker.DockerDesktop
winget install -e --id Kubernetes.kubectl
winget install -e --id Kubernetes.kind
winget install -e --id Helm.Helm
```
If winget can't find an ID, run `winget search <name>`. Restart when asked, open Docker Desktop, and wait until it says the engine is running.

Docker Desktop on Windows uses WSL2, and its memory is capped in `%UserProfile%\.wslconfig`, not in the app. Create that file:
```
[wsl2]
memory=8GB
processors=4
```
Then run `wsl --shutdown` and reopen Docker Desktop.

**macOS:**
```bash
brew install --cask docker
brew install kubectl kind helm
```
Then open Docker Desktop and set Settings → Resources → Memory to 8 GB or more.

**Verify (Git Bash / Terminal):**
```bash
docker version && kubectl version --client && kind version && helm version
```

**Skip Linkerd for now** (Correction D). **Windows:** wherever the original runbook says `python3`, use `python`. Wherever it says `open <url>`, open the URL in your browser instead.

---

## 2. Corrections to the original runbook

### A. kind never exposes the NodePorts, so Prometheus sees nothing
- **The Problem:** Phase 1 ran a bare `kind create cluster`. A NodePort on kind exists only inside the kind node container. The docker-compose Prometheus scrapes `host.docker.internal:30000-30004,30080`, and nothing publishes those ports on your machine.
- **The Fix:** create the cluster with the config in `infra/kind-config.yaml` (it publishes ports 30000–30004 and 30080):
  ```bash
  kind delete cluster --name incident-commander 2>/dev/null
  kind create cluster --name incident-commander --config infra/kind-config.yaml
  ```
  The mappings can only be set at creation time, so an existing cluster must be deleted and recreated. I'm also dropping minikube as an option for this stack. Its NodePorts have the same reachability problem, with no equally simple fix.
- **The Impact:** without this fix every app target on the Prometheus targets page is DOWN. Grafana is empty, the z-score detector sees no data, the root-cause latency signal is blind, and the incident loop never fires.

### B. Phase 7's `--network host` does not work on Docker Desktop
- **The Problem:** the migration command used `docker run --network host`, which doesn't reach your machine's localhost on Docker Desktop.
- **The Fix:** run psql inside the Postgres pod:
  ```bash
  kubectl exec postgres-0 -c postgres -- psql -U incident_admin -d incident_commander \
    -c "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS confirmed_root_cause VARCHAR(100);"
  ```
  On a **fresh database, skip this step entirely.** `incident-engine` creates the table with that column already. It only matters if you have an old `incidents` table from before the accuracy-loop update. If the table doesn't exist yet, the command fails with "relation does not exist", which is harmless.
- **The Impact:** the original command hangs or fails, and you'd waste time debugging a step you probably don't need.

### C. `asyncpg==0.29.0` won't install on your Python 3.13.9
- **The Problem:** `chaos/requirements.txt` pinned `asyncpg==0.29.0`. Python 3.13 support first shipped in asyncpg 0.30.0 (confirmed against its release notes).
- **The Fix:** the zip contains `chaos/requirements.txt` pinned to `0.30.0`. Use a virtual environment so nothing touches your global Python:
  ```bash
  python -m venv .venv
  source .venv/Scripts/activate        # Windows Git Bash   (macOS/Linux: source .venv/bin/activate)
  pip install -r chaos/requirements.txt -r backend/notifier/requirements.txt
  ```
- **The Impact:** `pip install` fails on the whole file, which also blocks `httpx`, so even `traffic_generator.py` wouldn't run. The containers use Python 3.11 and are unaffected.

### D. Linkerd is optional for a first run
- **The Problem:** the original runbook made Linkerd look mandatory and ordered it before Helm. It adds a control plane plus a sidecar on every pod (roughly 1 GB extra), and it's one more thing that can fail.
- **The Fix:** skip the Linkerd lines in Phase 2. The chart works without it, because `linkerd.io/inject` is just an annotation that is ignored when no injector exists, and the mesh-policy resources are off by default (`meshPolicy.enabled: false`). Pods will show `1/1` instead of `2/2`. To add it later, install it and then run `kubectl rollout restart deployment` and `kubectl rollout restart statefulset postgres`.
- **The Impact:** this removes the heaviest and most failure-prone component from your first attempt, with no loss of functionality.

### E. Do not apply `infra/k8s/*.yaml`
- **The Problem:** those 9 raw manifests are from Milestone 1.J. The Helm chart replaced them, and applying both makes them fight over the same object names.
- **The Fix:** ignore the folder. Use only `helm upgrade --install`.
- **The Impact:** a stray `kubectl apply -f infra/k8s/` creates conflicting duplicate Deployments.

### F. The original runbook used Mac-only syntax
- **The Problem:** `brew`, `python3`, and `open` don't exist on Windows.
- **The Fix:** use the Windows column in Section 1, and run everything in Git Bash.
- **The Impact:** several commands fail with "command not found".

---

## 3. Staged bring-up (with a checkpoint per stage)

This order differs from the original runbook. It starts the docker-compose stack first, so the in-cluster workers find Kafka already running instead of crash-looping. It also tests one layer at a time.

### Stage 0: static validation (needs only Helm and Docker installed, no cluster)
```bash
bash scripts/preflight.sh            # must end with ALL CHECKS PASSED

cd infra/helm/incident-commander
[ -f values-secrets.yaml ]  || cp values-secrets.yaml.example values-secrets.yaml
[ -f values-customer.yaml ] || cp values-customer.yaml.example values-customer.yaml
grep -E "^(postgres|redis|api|otel|prometheus)Secrets:" values-secrets.yaml   # must print 5 lines
helm lint . -f values.yaml -f values-secrets.yaml -f values-customer.yaml
helm template incident-commander . -f values.yaml -f values-secrets.yaml -f values-customer.yaml > /dev/null && echo "chart renders"
cd ../../..
docker compose -f infra/docker-compose.yml config > /dev/null && echo "compose valid"   # unset-variable warnings are expected for now
```
**Checkpoint:** all four commands succeed. If the 5-line grep fails, your `values-secrets.yaml` is from an older version. Re-create it from the `.example` file in the repo.

### Stage 1: secrets and the docker-compose stack (needs Docker only)
1. Original runbook **Phase 4**: generate the secrets. Use `python`, not `python3`.
2. Fill in `infra/.env` and `observability/prometheus-web-config.yml` as in original **Phase 6**.
3. Use the **corrected** `docker-compose.yml` from original Phase 6. Optionally delete its `rabbitmq:` block, since nothing uses it.
   ```bash
   cd infra && docker compose up -d --build && docker compose ps
   ```

**Checkpoint:**
```bash
curl -s -o /dev/null -w "prometheus, no credentials: %{http_code}  (want 401)\n" "http://localhost:9090/api/v1/query?query=up"
curl -s -o /dev/null -w "prometheus, with credentials: %{http_code}  (want 200)\n" -u admin:YOUR_PROMETHEUS_PASSWORD "http://localhost:9090/api/v1/query?query=up"
curl -s http://localhost:3200/ready                     # tempo: "ready" (may take ~20s)
docker compose exec kafka /opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092 | head -1
```
Then open `http://localhost:3000` → Connections → Data sources → Prometheus → **Save & test**. It must be green. That proves the whole Grafana-to-Prometheus auth chain. App targets will show DOWN at this point, which is expected since no cluster exists yet.

### Stage 2: cluster and application (adds kind, kubectl, Helm)
```bash
kind delete cluster --name incident-commander 2>/dev/null
kind create cluster --name incident-commander --config infra/kind-config.yaml
```
Then original **Phase 2's metrics-server lines only (not Linkerd)**, **Phase 3** (build and load all 11 images), and **Phase 5** (`helm upgrade --install ... -f values.yaml -f values-secrets.yaml -f values-customer.yaml`).

**Checkpoint:**
```bash
kubectl get pods        # expect 13 pods Running, 1/1 each: 12 Deployments (11 app + redis) + postgres-0
kubectl run net-test --rm -i --restart=Never --image=busybox:1.36 -- nslookup host.docker.internal
curl -s -u admin:YOUR_PROMETHEUS_PASSWORD "http://localhost:9090/api/v1/targets" | grep -o '"health":"[a-z]*"' | sort | uniq -c
```
- Pods: no `ImagePullBackOff`. If you see one, an image wasn't loaded into kind (see Section 5).
- `nslookup` must return an IP. If it can't resolve `host.docker.internal`, tell me and I'll adapt the values. Pods can't reach Kafka, the collector, or Prometheus without it.
- Targets: you want **7 × "up"** (Prometheus plus the 6 app services). Any "down" means Correction A wasn't applied.

### Stage 3: telemetry flows end to end
Original **Phase 10** (port-forwards; the gateway is also reachable at `http://localhost:30080` now) and **Phase 11** (smoke test).

**Checkpoint:**
- `curl http://localhost:8006/graph -H "X-API-Key: <key>"` shows `gateway → auth/payment/inventory/recommendation` **and** `payment-service → postgres` and `payment-service → redis`. The last two were discovered from span data, not hand-typed.
- In Grafana → Explore → Tempo, search recent traces and open a `POST /checkout`. The waterfall should span all services.
- If the graph has the HTTP edges but not postgres/redis, the instrumentation library names its span attributes differently from the names `builder.py` looks for. Send me one raw span from the collector's logs (`docker compose logs otel-collector`).

### Stage 4: detection, reasoning, dashboard, paging
Original **Phase 8** (notifier), **Phase 9** (dashboard), **Phase 12** (lifecycle). Two practical notes:
- **Run steady traffic for at least 5 minutes before injecting latency.** The detector needs 10 samples at 15 seconds each (about 2.5 minutes) to build a baseline. Before that it correctly flags nothing.
- The detector already runs inside the cluster. Watch it with `kubectl logs -f deploy/zscore-detector` instead of starting it by hand.

**Checkpoint:** an incident appears on the dashboard, `payment-service` turns red on the map, the notifier prints (or sends) an alert, and after you resolve it with a confirmed cause, `/accuracy` returns a real number.

### Stage 5 (optional, later): Linkerd
Only after Stages 0–4 pass. See Correction D.

---

## 4. If your machine has 8 GB of RAM or less

The full stack (8 compose containers, 13 pods, Postgres, Kafka's JVM) wants roughly 6–8 GB. To reduce it:
1. Delete the `rabbitmq:` block from `docker-compose.yml`. Nothing uses it.
2. Skip Linkerd (already the default in this plan).
3. Set Docker's memory to 6 GB and close your browser tabs and IDE extensions during tests.
4. If it is still too tight, tell me. Loki, Promtail and Tempo aren't on the incident-detection path, and I can give you a trimmed compose file without them.

---

## 5. Quick troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ImagePullBackOff` / `ErrImageNeverPull` | Image not loaded into kind | `kind load docker-image <name>:latest --name incident-commander`, then `kubectl rollout restart deploy/<name>` |
| Prometheus app targets DOWN | Cluster created without `kind-config.yaml`, or `host.docker.internal` not resolving | Recreate the cluster with the config; run the `nslookup` test |
| `telemetry-consumer` crash-looping | Kafka not healthy yet, or `host.docker.internal:9094` unreachable | `docker compose ps`; start the compose stack before Helm |
| `401` from any API | API key differs between `values-secrets.yaml`, `backend/notifier/.env`, and `apps/incident-dashboard/.env.local` | Make all three identical, then `helm upgrade ...` and `kubectl rollout restart deploy` |
| Changed a secret, nothing changed | Pods read Secrets only at startup | `kubectl rollout restart deploy` |
| Dashboard shows CORS errors | Not served on port 5174, or the port-forwards aren't running | Use `http://localhost:5174`; check Phase 10 |
| Detector never flags | Baseline not built yet, or Prometheus password mismatch | Wait 5+ minutes of traffic; `kubectl logs deploy/zscore-detector` and look for 401 |
| Grafana panels empty | Prometheus password in `infra/.env` doesn't match the bcrypt hash | Regenerate both from one password; `docker compose up -d grafana prometheus` |
