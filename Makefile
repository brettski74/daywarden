# Local stack. The listen port and the CA directory come from .env.
# A value already in the environment wins. .env fills in the rest.
# Sourcing .env over the top would drop a prefix such as
# PARENT_NAMES=... make up. PARENT_PASSWORD used to survive that
# prefix because it was never written into .env. A value may use
# ${HOME} and other variables, as docker compose expands them.

load_env = set -a; while IFS= read -r line || [ -n "$$line" ]; do case "$$line" in ""|[\#]*) continue ;; esac; key=$${line%%=*}; if [ -z "$${!key+x}" ]; then eval "export $$key=\"$${line\#*=}\""; fi; done < .env; set +a

.PHONY: up down show-env

up:
	$(load_env); mkdir -p "$$CA_VOLUME_PATH" "$${DAYWARDEN_DATA_DIR:-$$HOME/daywarden}" && docker compose up -d --wait

down:
	docker compose down

show-env:
	@$(load_env); printf '%s\n' "$$PARENT_NAMES" "$$CA_VOLUME_PATH" "$$DAYWARDEN_DATA_DIR"
