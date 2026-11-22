# rail-rag-k8s

Runs a RAG assistant over EU railway law ([rail-regulation-rag](https://github.com/cardohso/rail-regulation-rag))
as an ML service on a local Kubernetes cluster (kind): Helm chart, health probes, autoscaling,
Prometheus and Grafana, tested under load and failure.

> **Status: work in progress (step 3 of 9).** The cluster scripts and the Helm chart exist; the
> real api image arrives in step 4, so the chart has only been run with a stub api. No result is
> claimed yet; the claim this repo is built to prove is in the box below.

**The claim to prove, with evidence:** the assistant runs on Kubernetes, scales with load,
survives pod failures and rolling updates without failed requests, and its health and latency
are visible and alerted on.

## Quickstart (cluster only, for now)

Needs Docker (8 CPUs and at least 7.5 GiB for its VM), kind, kubectl and Helm. For linting and
load tests: shellcheck, gitleaks, k6, kubeconform and chart-testing.

```bash
brew install kind kubectl helm shellcheck gitleaks k6 kubeconform chart-testing
make up      # create the 3-node kind cluster (about 1 minute)
make down    # delete it (about 6 seconds, safe to run twice)
```

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
