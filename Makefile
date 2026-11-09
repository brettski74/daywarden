# Local stack. The ports and the CA directory come from .env.
# A value already in the environment wins. .env fills in the rest.
# Sourcing .env over the top would drop a prefix such as
# PARENT_NAMES=... make up. PARENT_PASSWORD used to survive that
# prefix because it was never written into .env. A value may use
# ${HOME} and other variables, as docker compose expands them.

load_env = set -a; while IFS= read -r line || [ -n "$$line" ]; do case "$$line" in ""|[\#]*) continue ;; esac; key=$${line%%=*}; if [ -z "$${!key+x}" ]; then eval "export $$key=\"$${line\#*=}\""; fi; done < .env; set +a

VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
DIST_DIR := dist
PORTAL := policy/portal
PORTAL_INSTALLED := $(PORTAL)/node_modules/.package-lock.json

.PHONY: up down reload restart check logs show-env venv portal-deps test dist help

# make help lists each target that has a "## description" on its line.

# bin/dw loads .env the same way as load_env, so an exported value still wins.
# It also works out the ports from PORT_BASE, which Compose cannot do.
up: ## Check the policy, start the local stack, and wait until every service is healthy
	@bin/dw up

down: ## Stop the local stack and remove its containers
	@bin/dw down

reload: ## Check the policy and apply it without restarting a container
	@bin/dw reload

restart: ## Check the policy, then replace every container. Applies .env changes
	@bin/dw restart

check: ## Check the policy and list every error. Changes nothing
	@bin/dw check

logs: ## Show the last lines each service logged. Options and services with ARGS="-f decisions"
	@bin/dw logs $(ARGS)

show-env: ## Print PARENT_NAMES, the CA directory, and the data directory
	@$(load_env); printf '%s\n' "$$PARENT_NAMES" "$$CA_VOLUME_PATH" "$$DAYWARDEN_DATA_DIR"

# The venv is built once and rebuilt only when a requirements file changes.
venv: $(VENV)/.installed ## Create .venv with the test requirements

$(VENV)/.installed: requirements-dev.txt policy/requirements.txt
	python3 -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
	touch $@

# The portal's packages are installed once and again only when its lock file
# changes. Without Node this does nothing and the portal tests are skipped.
portal-deps: ## Install the parent portal's npm packages for its tests, when Node is installed
	@if command -v npm >/dev/null 2>&1; then $(MAKE) -q $(PORTAL_INSTALLED) || $(MAKE) --no-print-directory $(PORTAL_INSTALLED); \
	else echo "npm is not installed, so the parent portal tests will be skipped"; fi

$(PORTAL_INSTALLED): $(PORTAL)/package.json $(PORTAL)/package-lock.json
	cd $(PORTAL) && npm ci --no-audit --no-fund
	touch $@

test: venv portal-deps ## Run the tests, the portal's too. Pass pytest arguments with ARGS="tests/test_clips.py -q"
	$(VENV_PYTHON) -m pytest $(ARGS)

# Builds and saves the images. Does not change make up or .env.
dist: venv ## Package for another machine as dist/daywarden-<version>.tar.gz
	$(VENV_PYTHON) -m deploy.build --out $(DIST_DIR)

help: ## List the targets and what they do
	@awk -F ':[^#]*## ' '/^[a-z][a-z-]*:[^=]*## / { printf "  %-12s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
