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
**Verified (step 3):** a collection created in Qdrant survived `kubectl delete pod rail-rag-qdrant-0`
(the pod came back on the same PVC). Qdrant runs as uid 1000 with a read-only root filesystem; only
`/qdrant/storage`, `/qdrant/snapshots` and `/tmp` are writable. The image defaults to root and its
data directory is root-owned, so `fsGroup: 1000` on the pod is what makes the volume writable. One
harmless warning remains: it cannot write its `.qdrant-initialized` marker.

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

**Result:** kind's default plugin (kindnet) enforces NetworkPolicy, so Calico is not needed.
`tests/netpol-test.sh` checks 7 cases; each "must be blocked" check has a control that must succeed.
With the policies deleted, 4 checks fail (the four blocks); with them installed, all 7 pass.
Qdrant accepts only the api and the index Job and has no egress. The api accepts traffic from its
own namespace and the `monitoring` namespace, and may call only Qdrant, DNS and, when the real
generator is on, public HTTPS (private ranges excluded).
**Limit:** policies match on labels, so any pod that carries the api's labels in this namespace is
trusted. Restricting who may create pods is RBAC's job, not NetworkPolicy's.

## D10. Secrets

The Kubernetes Secret is created by hand from the user's own `.env`; the repo only documents the
command. No key is ever committed, and CI runs the fake generator only.

## D11. The index Job is a plain Job, not a Helm hook

**Chosen:** a normal Job whose name carries a hash of the image tag and `index.revision`.
**Why not a `post-install` hook:** with `helm install --wait`, Helm waits for the api to be ready
before it runs post-install hooks, but the api's startup probe waits for the index. That deadlocks
until the timeout. A normal Job runs in parallel; the startup probe simply waits for it.
**Why the hash in the name:** a Job's pod template is immutable, so an upgrade that changes the
image must create a new Job. Unchanged values give the same name and Helm leaves it alone.
**Cost:** old Jobs are removed by Helm on upgrade, so their logs are gone; failed Jobs keep theirs.

## D12. Zero-downtime rollout settings

`maxSurge: 1, maxUnavailable: 0` starts a new pod and waits for readiness before removing an old
one. On deletion the `preStop` sleep (the native `sleep` action, Kubernetes 1.30+, so the image
needs no shell) keeps the pod serving while endpoint removal propagates, then SIGTERM lets uvicorn
drain. A PodDisruptionBudget (`maxUnavailable: 1`) limits voluntary evictions such as a node drain.
Pods spread across nodes with a soft constraint (`ScheduleAnyway`), so a single node never stops
scheduling. **Claimed only after step 7 measures it**; step 3 sets the mechanism, not the result.

## D13. Provisional resources, and test scaffolding

Resource requests and limits in `values.yaml` are marked PROVISIONAL and are replaced by measured
values in step 4. `tests/stub-api/` is a throwaway server with the same probe paths, used only to
exercise the chart before the real image exists; it is removed once step 4 lands.
Qdrant is pulled by the nodes from Docker Hub rather than `kind load`-ed: `kind load` fails on the
multi-arch Qdrant image under Docker Desktop's image store ("content digest not found").
