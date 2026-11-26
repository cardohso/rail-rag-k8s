.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

help: ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

up: ## Create the kind cluster and install everything
	scripts/up.sh

down: ## Delete the cluster
	scripts/down.sh

status: ## Nodes and pods
	kubectl --context kind-rail-k8s get nodes,pods -A

image: ## Build the api image (runs its tests) and load it into kind
	scripts/build-image.sh

monitoring: ## Install Prometheus, Alertmanager and Grafana
	scripts/install-monitoring.sh

deploy: ## Install or upgrade the rail-rag release with the dev values
	helm upgrade --install rail-rag charts/rail-rag -n rail --create-namespace -f charts/rail-rag/values-dev.yaml

baseline: ## Measure the memory of the empty cluster
	scripts/measure-baseline.sh

machine: ## Print machine and tool versions as JSON
	scripts/machine-info.sh

lint: ## shellcheck, chart validation, chart-testing, secret scan
	shellcheck -x scripts/*.sh tests/*.sh
	scripts/chart-validate.sh
	ct lint --all --config ct.yaml
	gitleaks detect --source . --no-banner --redact

chart-validate: ## helm lint + kubeconform for every values overlay (no yamllint needed)
	scripts/chart-validate.sh

netpol-test: ## Prove the NetworkPolicies are enforced (needs a running release)
	tests/netpol-test.sh

alert-test: ## Take Qdrant down and check the 503, the Ready pods and the alert (about 5 min)
	tests/alert-qdrant-test.sh

smoke-test: ## Probes, one question and the metrics (needs a release with the fake generator)
	tests/smoke-test.sh

quality-gate: ## goldpass with the real generator (needs your own Secret; uses your quota)
	scripts/quality-gate.sh

secrets: ## Secret scan of the working tree and git history
	gitleaks detect --source . --no-banner --redact

.PHONY: help up down status image monitoring deploy alert-test baseline machine lint chart-validate netpol-test smoke-test quality-gate secrets
