# rail-rag-k8s

Runs a RAG assistant over EU railway law ([rail-regulation-rag](https://github.com/cardohso/rail-regulation-rag))
as an ML service on a local Kubernetes cluster (kind): Helm chart, health probes, autoscaling,
Prometheus and Grafana, tested under load and failure.

> **Status: work in progress (step 5 of 9).** The cluster, Helm chart, api image, Prometheus alerts
> and Grafana dashboard exist and have been run once each. Autoscaling, load and failure tests
> (steps 6 and 7) have not been done, so no result is claimed yet; the claim this repo is built to
> prove is in the box below.

**The claim to prove, with evidence:** the assistant runs on Kubernetes, scales with load,
survives pod failures and rolling updates without failed requests, and its health and latency
are visible and alerted on.

## Quickstart (cluster only, for now)

Needs Docker (8 CPUs and at least 7.5 GiB for its VM), kind, kubectl and Helm. For linting and
load tests: shellcheck, gitleaks, k6, kubeconform and chart-testing.

```bash
brew install kind kubectl helm shellcheck gitleaks k6 kubeconform chart-testing
make up          # create the 3-node kind cluster (about 1 minute)
make image       # build the api image, run its tests, load it into kind (first build is slow)
make monitoring  # Prometheus, Alertmanager, Grafana (about 1 minute)
make deploy      # install the chart; the api waits for the index job (about 5 minutes)
make down        # delete everything (about 6 seconds, safe to run twice)
```

Grafana (user `admin`, password `admin`, local only): `kubectl -n monitoring port-forward
svc/kps-grafana 3000:80`, then open the `rail-rag` dashboard. The one-command setup arrives in
step 9.

Design decisions and their trade-offs: [docs/DESIGN.md](docs/DESIGN.md).

## Secrets

The repo never contains an API key, and the default generator is a fake one that needs none. To
use the real Gemini generator, create the Secret yourself from your own `.env`
(only `GEMINI_API_KEY` is read; see `.env.example`):

```bash
kubectl -n rail create secret generic rail-rag-secrets --from-env-file=.env
helm upgrade rail-rag charts/rail-rag -n rail --reuse-values --set generator.provider=gemini
```

## Licence

MIT
