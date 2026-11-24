MDLINT ?= $(shell which markdownlint)
NIXIE ?= $(shell which nixie)
MDFORMAT_ALL ?= $(shell which mdformat-all)
TOOLS = $(MDFORMAT_ALL) ruff ty $(MDLINT) $(NIXIE) uv
VENV_TOOLS = pytest
SHELL := bash

.PHONY: help all clean build build-release lint fmt check-fmt \
	markdownlint nixie test typecheck $(TOOLS) $(VENV_TOOLS)

.DEFAULT_GOAL := all

all: build check-fmt test typecheck

build: uv ## Build virtual-env and install deps
	uv venv --allow-existing
	uv sync --group dev

build-release: ## Build artefacts (sdist & wheel)
	python -m build --sdist --wheel

clean: ## Remove build artifacts
	rm -rf build dist *.egg-info \
	  .mypy_cache .pytest_cache .coverage coverage.* \
	  lcov.info htmlcov .venv
	find . -type d -name '__pycache__' -print0 | xargs -0 -r rm -rf

define ensure_tool
	@command -v $(1) >/dev/null 2>&1 || { \
	  printf "Error: '%s' is required, but not installed\n" "$(1)" >&2; \
	  exit 1; \
	}
endef

define ensure_tool_venv
	@uv run which $(1) >/dev/null 2>&1 || { \
	  printf "Error: '%s' is required in the virtualenv, but is not installed\n" "$(1)" >&2; \
	  exit 1; \
	}
endef

ifneq ($(strip $(TOOLS)),)
$(TOOLS): ## Verify required CLI tools
	$(call ensure_tool,$@)
endif


ifneq ($(strip $(VENV_TOOLS)),)
.PHONY: $(VENV_TOOLS)
$(VENV_TOOLS): ## Verify required CLI tools in venv
	$(call ensure_tool_venv,$@)
endif

fmt: ruff $(MDFORMAT_ALL) ## Format sources
	ruff format
	ruff check --select I --fix
	$(MDFORMAT_ALL)

check-fmt: ruff ## Verify formatting
	ruff format --check
	# mdformat-all doesn't currently do checking

lint: ruff ## Run linters
	ruff check

SERENA_VERSION ?= 0.1.3
SERENA_DIR := $(HOME)/git/serena-$(SERENA_VERSION)
# Optional: set SERENA_SHA256 to verify the downloaded archive.
# Compute the checksum via `sha256sum <file>` and export SERENA_SHA256=<hash>.
SERENA_SHA256 ?=

download-serena:
	@if [ ! -d "$(SERENA_DIR)" ]; then \
	set -euo pipefail; \
	tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT; \
	url=https://github.com/oraios/serena/archive/refs/tags/v$(SERENA_VERSION).tar.gz; \
	curl --fail --silent --show-error --location "$$url" -o "$$tmp/serena.tgz"; \
	if [ -n "$(SERENA_SHA256)" ]; then \
	echo "$(SERENA_SHA256)  $$tmp/serena.tgz" | sha256sum -c -; \
	fi; \
        mkdir -p "$(dir $(SERENA_DIR))"; \
        tar -xzf "$$tmp/serena.tgz" -C "$$tmp"; \
	rand=$$PPID.$$RANDOM; \
	mv "$$tmp"/serena-$(SERENA_VERSION) "$(SERENA_DIR).$$rand" && \
	mv -T "$(SERENA_DIR).$$rand" "$(SERENA_DIR)"; \
	rm -rf "$$tmp"; \
fi

typecheck: build ty download-serena ## Run typechecking
	ty check --extra-search-path $(SERENA_DIR)/src
	
markdownlint: $(MDLINT) ## Lint Markdown files
	find . -type f -name '*.md' \
	  -not -path './.venv/*' -print0 | xargs -0 $(MDLINT)

nixie: $(NIXIE) ## Validate Mermaid diagrams
	find . -type f -name '*.md' \
	  -not -path './.venv/*' -print0 | xargs -0 $(NIXIE)

test: build uv pytest ## Run tests
	SERENA_DIR=$(SERENA_DIR) uv run pytest -v

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS=":"; printf "Available targets:\n"} {printf "  %-20s %s\n", $$1, $$2}'
