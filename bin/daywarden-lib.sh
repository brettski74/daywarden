# Shared by the daywarden host commands: dw, rm-attempts, add-parent,
# daywarden-service, and install.sh. Sourced, not run.
#
# The caller sets root to the directory the commands act on. That is the
# repository for bin/ in a clone, and ~/daywarden for an installed package.
# Both hold docker-compose.yml, .env, and config/.

DW_SERVICES=(decisions observations proxy)
DW_UNIT=daywarden.service

dw_user() {
    printf '%s\n' "${USER:-$(id -un)}"
}

# Export each KEY=value line of an env file. A variable already in the
# environment wins, as with make up. A value may use ${HOME} and other
# variables, as docker compose expands them.
dw_load_env() {
    local line key
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in "" | \#*) continue ;; esac
        key=${line%%=*}
        [[ $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
        if [ -z "${!key+x}" ]; then
            eval "export $key=\"${line#*=}\""
        fi
    done <"$1"
}

# Stop with the install advice unless root holds an installed daywarden.
dw_require_installed() {
    local prog=$1 file
    for file in docker-compose.yml .env; do
        if [ ! -f "$root/$file" ]; then
            echo "$prog: daywarden is not installed in $root: $file is missing. Run install.sh again." >&2
            exit 1
        fi
    done
}

# Check the install, move to root so relative paths in .env resolve the way
# Compose resolves them, and load .env.
dw_prepare() {
    dw_require_installed "$1"
    cd -- "$root"
    dw_load_env "$root/.env"
    DW_PROJECT=${COMPOSE_PROJECT_NAME:-daywarden}
}

dw_compose() {
    docker compose --project-directory "$root" "$@"
}

dw_data_dir() {
    if [ -n "${DAYWARDEN_DATA_DIR:-}" ]; then
        printf '%s\n' "$DAYWARDEN_DATA_DIR"
    elif [ -f "$root/VERSION" ]; then
        printf '%s\n' "$root/data"
    else
        printf '%s\n' "$HOME/daywarden"
    fi
}

# True when a container of this Compose project, or of one of its services,
# is running.
dw_running() {
    local filters=(--filter "label=com.docker.compose.project=${DW_PROJECT:-daywarden}")
    [ -n "${1:-}" ] && filters+=(--filter "label=com.docker.compose.service=$1")
    [ -n "$(docker ps -q "${filters[@]}" 2>/dev/null)" ]
}

dw_require_running() {
    if ! dw_running decisions; then
        echo "daywarden is not running. Start it with dw up." >&2
        exit 1
    fi
}

# Print "service<TAB>state" for each service: healthy, starting, unhealthy,
# or not running.
dw_service_states() {
    local listing service state health name
    local -A seen=()
    listing=$(dw_compose ps -a --format '{{.Service}}	{{.State}}	{{.Health}}' 2>/dev/null) || listing=""
    while IFS=$'\t' read -r service state health; do
        [ -n "$service" ] || continue
        if [ "$state" = running ]; then
            seen[$service]=${health:-running}
        else
            seen[$service]="not running"
        fi
    done <<<"$listing"
    for name in "${DW_SERVICES[@]}"; do
        printf '%s\t%s\n' "$name" "${seen[$name]:-not running}"
    done
}

# Create the CA and data directories, so Docker does not create them owned
# by root, then start the stack and wait until every service is healthy.
dw_compose_up() {
    local data bad="" service state failed=()
    if [ -z "${CA_VOLUME_PATH:-}" ]; then
        echo "dw: CA_VOLUME_PATH is not set in $root/.env." >&2
        return 1
    fi
    data=$(dw_data_dir)
    mkdir -p -- "$CA_VOLUME_PATH" "$data"
    if dw_compose up -d --wait --wait-timeout 180; then
        return 0
    fi
    while IFS=$'\t' read -r service state; do
        if [ "$state" != healthy ]; then
            bad+="${bad:+, }$service ($state)"
            failed+=("$service")
        fi
    done < <(dw_service_states)
    echo "dw: these services did not become healthy: ${bad:-none reported, but docker compose up failed}" >&2
    for service in "${failed[@]}"; do
        if [ -n "$(dw_compose ps -a -q "$service" 2>/dev/null)" ]; then
            echo "The last lines $service logged:" >&2
            dw_compose logs --no-color --no-log-prefix --tail 8 "$service" 2>&1 | sed 's/^/  /' >&2 || true
            break
        fi
    done
    return 1
}

dw_user_manager() {
    systemctl --user show-environment >/dev/null 2>&1
}

dw_user_manager_advice() {
    echo "  This user's systemd manager cannot be reached with systemctl --user, for example in a su session."
    echo "  Fix: log in as $(dw_user) directly, such as over ssh, and run dw enable."
}

dw_enabled() {
    [ "$(systemctl --user is-enabled "$DW_UNIT" 2>/dev/null)" = enabled ]
}

dw_docker_starts_at_boot() {
    local unit
    for unit in docker.service docker.socket; do
        [ "$(systemctl is-enabled "$unit" 2>/dev/null)" = enabled ] && return 0
    done
    return 1
}

dw_unit_path() {
    printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$DW_UNIT"
}

dw_unit_text() {
    cat <<EOF
# Written by dw enable. install.sh rewrites it on an upgrade while daywarden
# is enabled. Use dw enable and dw disable rather than editing it.
[Unit]
Description=daywarden household proxy

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart="$root/bin/daywarden-service" start
ExecStop="$root/bin/daywarden-service" stop
TimeoutStartSec=6min
TimeoutStopSec=2min

[Install]
WantedBy=default.target
EOF
}

# Write the user service file. True when the file changed.
dw_write_unit() {
    local path text
    path=$(dw_unit_path)
    text=$(dw_unit_text)
    if [ -f "$path" ] && [ "$(<"$path")" = "$text" ]; then
        return 1
    fi
    mkdir -p -- "$(dirname -- "$path")"
    printf '%s\n' "$text" >"$path.tmp"
    mv -- "$path.tmp" "$path"
}
