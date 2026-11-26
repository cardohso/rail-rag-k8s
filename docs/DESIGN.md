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

**Chosen:** a deterministic generator, selected by a config flag, that sleeps a seeded 300-900 ms
**per call**. One `/ask` makes three generator calls (rewrite, grade, generate), so a request that
reaches the generator costs 0.9-2.7 s of waiting, roughly what three calls to a small hosted model
cost. The delay is a hash of (seed, prompt, text): the same question always costs the same, on any
pod, so a run can be repeated. A question the retrieval floor refuses makes one generator call (the rewrite) instead of three.
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
- **readiness:** local state only (startup finished). Must not check Qdrant. Not-shutting-down is
  not checked: uvicorn closes its listener on SIGTERM, and the `preStop` sleep (D12) already covers
  the time the endpoint needs to leave the Service.
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
exercise the chart before the real image existed; removed in step 4.
Qdrant is pulled by the nodes from Docker Hub rather than `kind load`-ed: `kind load` fails on the
multi-arch Qdrant image under Docker Desktop's image store ("content digest not found").

## D14. The wrapper (step 4)

`wrapper/rail_k8s` is installed next to upstream, unmodified, at commit c7c371f (`image/Dockerfile`
downloads that commit's archive). It adds only what Kubernetes needs:
- `RemoteQdrantStore`: upstream's `QdrantStore` with a server client instead of a local folder.
- `build_pipeline`: mirrors upstream's `Pipeline.from_settings`, which hard-wires the local store.
- `Service`: loads the model in a background thread so the port is open and `/startupz` can report
  `loading-model` or `waiting-for-index`; `/ask` answers 503 until ready.
- `/livez`, `/readyz`, `/startupz`, `/metrics`; request ID header; one JSON log line per request.
- `DeadlineLLM`: a real-provider call that misses `GENERATOR_TIMEOUT_SECONDS` becomes a 503
  instead of waiting through upstream's retries (up to minutes). Python cannot kill the thread, so
  the abandoned call finishes in the background; the pool is capped at 32.
`tests/test_contract.py` fails if upstream renames anything the wrapper relies on. Probes and
`/metrics` are excluded from the in-flight gauge and request counters, so scraping never moves the
autoscaler.

## D15. Indexing memory: the first limit was wrong

The first install used a provisional 1 Gi limit for the index Job, and it was OOM-killed on all
4 attempts. Embedding the 1,589 passages in this container (`LocalEmbedder`, one process, idle
Docker VM, `ru_maxrss`):

| embedding batch | peak memory | time |
|---|---|---|
| 8 | 565 MiB | 243 s |
| 32 (upstream default) | 1,582 MiB | 1,054 s |

The smaller batch is better on both counts, so the index Job uses 8. The api is unaffected: it
embeds one query at a time. My first measurement printed "2" because I divided `ru_maxrss` (KiB on
Linux) by 1024 twice; I only noticed because the Job was being killed at 1 Gi.
**Also found at the same time:** Helm renders `1000000` as `1e+06` inside `quote`, which the real
api rejected as an integer. The stub never read that variable. Numeric values now pass through
`int64`.

**Measured api resources (step 4).** One api pod, fake generator, 4 concurrent clients through
`kubectl port-forward`, cgroup counters read inside the pod. Machine: Apple M1 Pro, Docker VM
8 CPUs and 7.7 GiB. Single run, a first estimate: the step-7 load tests repeat it 3 times.

| | value |
|---|---|
| memory after start (model loaded, index ready) | 233 MiB |
| memory peak after 148 requests | 247 MiB |
| CPU per request | 0.24 CPU-s (35 s over 148 requests) |
| index Job peak (embedding at batch 8) | 667 MiB |

At 0.24 CPU-s per request one CPU serves about 4 requests per second, so CPU, not the generator
wait, is what limits a pod. That matters for D7: the CPU trigger will fire before in-flight does
at high rate. `values.yaml` now has requests 250m / 320Mi and a 512Mi memory limit for the api.

## D16. Monitoring: kube-prometheus-stack, scoped to this cluster

**Chosen:** kube-prometheus-stack 93.10.0 in the `monitoring` namespace
(`observability/kube-prometheus-stack-values.yaml`, `scripts/install-monitoring.sh`). The chart
adds a `ServiceMonitor` (scrape `/metrics`), a `PrometheusRule` with 7 alerts and a dashboard
ConfigMap that Grafana's sidecar loads; all three are off by default and on in `values-dev.yaml`,
because they need the stack's CRDs.
**Why this stack:** it is what teams actually run, and the CRDs make the scrape config and alerts
part of the release. **Trimmed for a laptop:** etcd, scheduler, controller-manager and kube-proxy
scraping are off (kind binds them to localhost, so they would only be failing targets), 12 h
retention, no persistent volume (metrics are disposable; results are saved by scripts), explicit
memory limits on every component, Grafana's stock dashboards off.
**Alerts and what they watch:** `RailApiDown`, `RailApiScrapeDown`, `RailApiHighErrorRate` (5xx
share of `/ask` over 5 min, with a minimum-traffic guard), `RailApiHighLatency` (p95 above 4 s),
`RailPodRestarting`, `RailQdrantDown`, `RailQdrantErrors`. Thresholds are chart values. The 4 s p95
sits above the fake generator's ceiling of about 2.7 s, so it fires on saturation, not normal
operation; step 7 checks that against real runs.
**Alerts are not sent anywhere.** Alertmanager runs and shows them, but no receiver (email, chat)
is configured: that needs credentials, and nothing in this repo should hold any.
**Probes and `/metrics` are not counted as load** (see D14), so scraping never moves the
in-flight metric the autoscaler reads.
**A problem on first install:** Grafana 13 started slowly on a busy Docker VM and the chart's
liveness probe (about 160 s in total) killed it mid-start, three times, until Helm timed out. I
raised the probe's initial delay to 300 s and re-ran, and it started in under a minute. I changed
that and the load went away at about the same time, so I cannot say which one fixed it.

**Measured** (`scripts/measure-baseline.sh`, `docker stats` per node, Apple M1 Pro, Docker VM 8 CPUs
and 7.7 GiB; one reading each, in [results/](../results/)):

| cluster state | total node memory |
|---|---|
| empty | 929 MiB |
| rail-rag running (2 api pods, Qdrant, index done) | 2,790 MiB |
| plus kube-prometheus-stack | 4,519 MiB (57% of the VM) |

The stack costs about 1.7 GiB, which leaves about 3.4 GiB for scaling the api (each pod about
250 MiB) and for page cache. The load generator runs on the host, outside the VM.

**Outage test** (`tests/alert-qdrant-test.sh`, `make alert-test`). With Qdrant scaled to 0:
`/ask` answers 503 in 4 s, both api pods stay Ready, and `RailQdrantDown` fires after 62 s (the
rule waits 1 minute). After Qdrant returns, `/ask` works and the alert clears. 4 s is not "instant":
it is the rewrite call (up to 0.9 s) plus the 2 s Qdrant timeout plus overhead. The first run
answered 503 in 9 s: a connect to a Service with no ready pods does not get refused, it hangs
(10.7 s measured from inside a pod), so the client timeout is what bounds the wait. It was 5 s;
it is now `qdrant.clientTimeoutSeconds: 2`. A second run of the test would give a second number;
this is one run of each version.

## D17. Autoscaling: fixed-size pods, and benchmarks off the laptop

**Prerequisites (step 6):** kind has no resource-metrics API, so even a CPU HPA cannot work until
metrics-server is installed (`scripts/install-autoscaling.sh`, metrics-server 3.14.0 with
`--kubelet-insecure-tls` because kind's kubelets use self-signed certificates, and KEDA 2.21.1).
The chart's `api.autoscaling.mode` is `hpa` (CPU only) or `keda` (CPU and in-flight per pod);
scale-up is immediate, scale-down waits 120 s and removes one pod per minute.

**Load comes from inside the cluster** (`scripts/k6-run.sh`, k6 2.4.0 as a pod). A
`kubectl port-forward` sends every request to one pod, so it cannot test load balancing or
scaling. k6 opens a new connection per request: with keep-alive, kube-proxy balances
connections, not requests, so each virtual user would stay on the pod it first reached and pods
added mid-run would get no traffic.

**A pod needs a fixed size for scaling to mean anything.** The first clean capacity run (one pod,
no CPU limit) scaled linearly to 8.1 requests/s at 16 concurrent users, p95 flat at 2.9 s, using
2.4 cores, and never saturated: the embedding runtime starts one thread per core the container can
see (all 8 of the VM's), so a single pod could take the whole machine and adding pods would add
nothing. Each api pod now has CPU request = limit, and the runtime is capped to one thread
(`api.embedThreads`, through `rail_k8s.embed.ThreadedEmbedder`; a contract test checks it returns
the same vectors as upstream's embedder, within 1e-5). This replaces the "no CPU limit" choice
made in step 4: a limit without the thread cap would throttle eight threads inside one CPU.

**Benchmarks run on GitHub Actions, not on the laptop** (`.github/workflows/bench.yml`). Three
capacity runs on the laptop are discarded, and the reason is the point:

| run | what happened | why it is not used |
|---|---|---|
| 1 | p95 30 s at 2 users, 3.8% failed | host CPU taken by other work (load average 48); the VM's CPU-pressure signal was 0.4-0.98 |
| 2 | clean: 0 failures, CPU pressure 0.06-0.22 | used above, as the reason for fixed-size pods |
| 3 | took 2,441 s instead of 400; one request "lasted" 1,229 s | the Mac ran out of memory (12.7 of 13.3 GB swap in use) and paused the whole VM |

A 16 GB laptop that also runs a browser, an editor and other jobs cannot give the Docker VM a
stable 8 GB. The GitHub runner (4 vCPUs, 16 GB, arm64 like the laptop) runs nothing else, and
anyone can rerun the workflow. On 4 vCPUs the pods are smaller (500m, `values-bench.yaml`) and
at most 4, which leaves 2 cores for the control plane, Prometheus, Qdrant and k6. Shared runners
have their own noise, so each scenario runs 3 times and the spread is reported. Every run also
records the host's load average (`results/raw/<run>.host.json`).

**Measured on the runner** (workflow run 45672935010, 3 runs per scenario; data in
`results/bench/45672935010/`, tables in `results/bench-45672935010.md` from
`scripts/bench_report.py`). The laptop's 0.28 CPU-s per request was contention: on the runner a
request costs 0.033 CPU-s at every load level.

- *One pod saturates near 14.5 requests/s.* Throughput grows linearly to 32 users (14.1-14.5
  req/s, p95 2.9 s), then stays flat at 48 (14.2-14.7 req/s) while p95 rises to 4.9 s. At that
  point the pod is at its CPU limit (0.47 of 0.5) and at the 32 generator calls it can run at once
  (`DeadlineLLM`'s pool); this test cannot say which binds first, since both arrive together.
- *A 40-user burst:* the CPU HPA scales to 2 pods, 36-56 s after the burst starts, and stops
  there, because two pods sit at 68% of their request, just under the 70% target. KEDA scales on
  in-flight requests first (22-42 s to 2 pods) and on to 4. Neither failed a request. Over the
  whole run p95 is 2.47-2.70 s with the HPA and 2.23-2.26 s with KEDA; with KEDA it equals the
  unloaded p95 (2.22 s), with the HPA the extra is the minute one pod carries the burst alone.
  After the burst, the HPA is back to 1 pod in about 2 minutes and KEDA in about 4 (the 120 s
  window, then one pod a minute).
- *Targets:* 10 in flight per pod, about a third of where one pod saturates, and CPU 70% as the
  second trigger. CPU alone works but reacts later and less, because a pod waiting on the
  generator uses little CPU per request in flight.
- *Two caveats.* Prometheus's p95 (2.8 s unloaded) is higher than k6's (2.2 s) because it
  interpolates inside the 2.5-5 s histogram bucket; the tables say which one they use. One request
  of 4,145 failed in capacity run 3 with no 5xx recorded by the api, so it never got an HTTP
  answer; k6 now logs each failure (`ASK_FAIL` lines in `<run>.k6.log`) so the next one has a
  cause.

**Helm 4 and `kubectl scale` conflict:** Helm 4 applies manifests server-side, so after a
`kubectl scale` it refuses to upgrade the replica count it no longer owns. Scripts set replicas
through Helm values only.

## D18. Failure tests: what survives, and the one thing that cannot

**The test** (`scripts/chaos.sh`, on the GitHub runner): 3 api pods of 500m, 16 VUs for 5 minutes
(about 8.4 requests/s, so 2 pods could carry it alone), one fault 90 s in, 3 runs per fault. k6
runs on the node that holds Qdrant, so the drain never removes the test's own client, and the
drained node is the other worker because Qdrant's volume is bound to its node. Results for run
45812596011 are in `results/chaos-45812596011.md` (from `scripts/chaos_report.py`), raw data in
`results/chaos/45812596011/`.

| fault | failed requests (3 runs, ~2,740 each) | p95 | 3 pods ready, from the fault |
|---|---|---|---|
| graceful pod delete | 0, 0, 0 | 2.22 s | 7-8 s |
| rolling restart (maxSurge 1, maxUnavailable 0) | 0, 0, 0 | 2.22 s | 26 s |
| node drain | 0, 0, 0 | 2.22 s | not recorded (below) |
| SIGKILL of one api container | 7, 13, 12 | 2.22 s | 11, 22, 30 s |

**Graceful removal loses nothing.** The preStop sleep (5 s) keeps a pod serving while it leaves
the Service, then SIGTERM lets uvicorn finish in-flight requests. During the drain the
PodDisruptionBudget refused the second api pod's eviction twice ("would violate the pod's
disruption budget") until the first pod's replacement was ready, so at most one pod was ever
missing. p95 is the same as without a fault in every run.

**A crash loses the requests in flight, and that is a limit, not a bug.** Of the 7-13 failures
per run, 6-9 are `EOF`: requests that pod had been answering for 50-2,018 ms, which no server can
complete after SIGKILL. The other 1-6 are `connection refused`: new connections that reached the
pod in the moment between the kill and its removal from the Service; the last came 0.55 s after
the kill. After that the two other pods carry the load at the same p95. That is 0.25-0.47% of a
run's requests, all within one second. Kubernetes cannot hide it; the fix belongs in the client:
`/ask` only reads, so retrying once on a connection error is safe (README limitations, step 9). Recovery
grows 11, 22, 30 s because the same container was killed three times in 11 minutes and the kubelet
doubles its restart delay each time (crash backoff), which is the intended behaviour.

**Measurement fix:** `kubectl drain` returns only after its evictions finish, so in this run the
script's recovery timer started when the pods were already back and read 0 s. `chaos.sh` now
times every fault from the moment it is applied (`fault_to_ready_s`); the drain figure comes with
the next run. For the other faults, the table adds the script's fixed 3 s pause to the old timer.
