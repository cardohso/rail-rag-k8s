# Design decisions

Draft written at step 2. Each decision says what was chosen, why, and what it costs. Numbers marked
*to measure* are filled in by the step that measures them; none is a claim yet.

## D1. kind, 1 control plane + 2 workers

**Chosen:** kind with three nodes (`cluster/kind-config.yaml`).
**Why:** kind is already installed, and it is what GitHub Actions uses, so local and CI run the
same cluster. Two workers let a node drain and pod anti-affinity mean something. k3d would save a
few hundred MB, but the binding limit is Docker Desktop's ~7.7 GiB, not the choice of tool.
**Cost:** every node is a container sharing one Mac, so load generator, cluster and Prometheus
compete for the same 8 cores. Every result records this.
**Measured** (`make baseline`, [results/baseline-empty-cluster.json](../results/baseline-empty-cluster.json)):
the empty 3-node cluster uses 929 MiB (control plane 653, workers 128 and 148) of the 7,934 MiB
Docker VM, 12%. My step-1 estimate for the control plane and workers was ~1.2 GB, so it was
conservative. The rest of the stack (Prometheus, KEDA, Qdrant, up to 5 api pods) is still to measure.

## D2. Build our own image from `rail-regulation-rag` pinned to a commit

**Chosen:** a Dockerfile in this repo that installs the upstream project at one commit
(c7c371f at time of writing) and adds a thin wrapper package.
**Why:** the published ghcr image is amd64 only; kind on Apple Silicon runs arm64 nodes, so it
would run under emulation and make every CPU number meaningless. The upstream repo is not changed.
**Cost:** the wrapper hooks into upstream internals (the provider registry and
`Pipeline.from_settings`). A contract test and the commit pin contain the risk.

## D3. Fake generator with a fixed, seeded delay

**Chosen:** a deterministic generator, selected by a config flag, that sleeps a seeded 300-900 ms.
**Why:** load tests must not spend free-tier quota. Without a delay, a pod is CPU-bound and the
"requests in flight" metric is meaningless; with one it behaves like production, mostly waiting.
**Cost:** latency and capacity under load are for the fake, not for Gemini. The README says so.

## D4. Qdrant as a StatefulSet with a PVC, loaded by a Job

**Chosen:** Qdrant server, one replica, persistent volume; a Job builds the index and skips the
rebuild if the passage count already matches.
**Why:** it is the production shape (Azure AI Search is also external) and it shows stateful
workloads. **Honest trade-off:** the index is 9 MB and read-only, so baking it into each pod would
be simpler and remove a single point of failure.
**Cost:** kind's default storage pins the volume to one node, so draining that node leaves Qdrant
Pending. Reported as a limitation; the drain test targets the other worker.

## D5. Three probes with different jobs

- **startup:** model loaded, Qdrant reachable, expected passage count present. Slow allowed.
- **readiness:** local state only (startup done, not shutting down). Must not check Qdrant.
- **liveness:** the process answers `/livez`. Nothing else.

**Why readiness skips Qdrant:** Qdrant is shared by every api pod. If readiness checked it, one
Qdrant blip would remove all pods from the Service at once; callers would get connection errors
instead of a clear 503, and the HPA would flap. Qdrant down returns a fast 503 and a `QdrantDown`
alert fires. **Liveness stays minimal** so a slow dependency never causes a restart loop.

## D6. No separate embedding service

**Chosen:** embeddings stay in the api process.
**Why:** a bge-small query embedding should take milliseconds next to seconds for the generator;
splitting adds a network hop and another Deployment to tune.
**Revisit if:** step 4 measures embeddings above 30% of api CPU.

## D7. Autoscaling: KEDA on requests in flight per pod

**Chosen:** KEDA with a CPU trigger and a Prometheus trigger on in-flight requests per pod.
**Why not Prometheus Adapter:** KEDA keeps the query in one manifest next to the scaler;
Adapter needs separate rewriting rules that commonly fail with "metric not found".
KEDA still creates an ordinary HPA, so `kubectl describe hpa` shows each decision.
**Why in-flight, not p95:** concurrency = rate x latency, so it rises as soon as traffic nears a
pod's capacity. p95 rises only once requests already queue. p95 stays as an alert.
**Cost:** one more operator in a memory-limited cluster.

## D8. One uvicorn process per pod; graceful shutdown

**Chosen:** one worker per pod; `preStop` sleep 5 s, then uvicorn drains in-flight requests;
`terminationGracePeriodSeconds: 30`; the wrapper caps real-generator time near 20 s.
**Why:** several workers per pod would load the model several times and blur per-pod metrics.
The preStop sleep lets the endpoint leave the Service before the pod stops accepting requests.
Upstream retries can run past 2 minutes, longer than any grace period, hence the cap.

## D9. NetworkPolicy needs proof

kind's default network plugin may not enforce policies. Step 3 includes a test where an unlabelled
pod must fail to reach Qdrant. If it does not fail, Calico is added (~250 MB).

## D10. Secrets

The Kubernetes Secret is created by hand from the user's own `.env`; the repo only documents the
command. No key is ever committed, and CI runs the fake generator only.
