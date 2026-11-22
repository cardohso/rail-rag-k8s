.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

help: ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

up: ## Create the kind cluster and install everything
	scripts/up.sh

down: ## Delete the cluster
	scripts/down.sh

status: ## Nodes and pods
	kubectl --context kind-rail-k8s get nodes,pods -A

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

secrets: ## Secret scan of the working tree and git history
	gitleaks detect --source . --no-banner --redact

.PHONY: help up down status baseline machine lint chart-validate netpol-test secrets
