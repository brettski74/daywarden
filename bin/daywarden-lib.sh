# Shared by the daywarden host commands: dw, rm-attempts, add-parent,
# daywarden-service, and install.sh. Sourced, not run.
#
# The caller sets root to the directory the commands act on. That is the
# repository for bin/ in a clone, and ~/daywarden for an installed package.
# Both hold docker-compose.yml, .env, and config/.

DW_SERVICES=(decisions observations proxy autoconfig)
DW_UNIT=daywarden.service
DW_PORT_KEYS=(PROXY_PORT POLICY_PORT PROXY_CONFIG_PORT)
DW_PORT_PROBLEMS=()

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
# Compose resolves them, load .env, and work out the ports. A port mistake
# stops only the commands that call dw_require_ports.
dw_prepare() {
    dw_require_installed "$1"
    cd -- "$root"
    dw_load_env "$root/.env"
    dw_ports || true
    dw_resolver
    DW_PROJECT=${COMPOSE_PROJECT_NAME:-daywarden}
}

# Work out and export PROXY_PORT, POLICY_PORT, and PROXY_CONFIG_PORT, so
# Compose, including config --hash, sees the ports dw uses. A port set in
# .env or the environment wins. The others are PORT_BASE, PORT_BASE+4, and
# PORT_BASE+8, and PORT_BASE is 8080 when it is left out. Compose cannot add
# numbers, so this is the one place that does. Each mistake goes in
# DW_PORT_PROBLEMS, and false when there is one.
dw_ports() {
    local base=${PORT_BASE:-8080} key value offset=0
    local -A seen=()
    DW_PORT_PROBLEMS=()
    if [[ $base =~ ^[0-9]{1,5}$ ]] && [ "$((10#$base))" -ge 1 ] && [ "$((10#$base))" -le 65535 ]; then
        base=$((10#$base))
    else
        DW_PORT_PROBLEMS+=("PORT_BASE must be a whole number from 1 to 65535, such as 8080, not '$base'.")
        base=""
    fi
    for key in "${DW_PORT_KEYS[@]}"; do
        value=${!key:-}
        if [ -z "$value" ]; then
            if [ -z "$base" ]; then
                offset=$((offset + 4))
                continue
            fi
            value=$((base + offset))
            if [ "$value" -gt 65535 ]; then
                DW_PORT_PROBLEMS+=("PORT_BASE $base puts $key at $base+$offset = $value, above 65535.")
                offset=$((offset + 4))
                continue
            fi
        elif [[ $value =~ ^[0-9]{1,5}$ ]] && [ "$((10#$value))" -ge 1 ] && [ "$((10#$value))" -le 65535 ]; then
            value=$((10#$value))
        else
            DW_PORT_PROBLEMS+=("$key must be a whole number from 1 to 65535, not '$value'.")
            offset=$((offset + 4))
            continue
        fi
        offset=$((offset + 4))
        if [ -n "${seen[$value]:-}" ]; then
            DW_PORT_PROBLEMS+=("${seen[$value]} and $key are both $value. Each port must be different.")
        fi
        seen[$value]=$key
        export "$key=$value"
    done
    [ ${#DW_PORT_PROBLEMS[@]} -eq 0 ]
}

# Print each port mistake and what was not done, such as "Nothing was
# restarted.". False when there is one.
dw_require_ports() {
    local problem
    [ ${#DW_PORT_PROBLEMS[@]} -eq 0 ] && return 0
    echo "dw: the ports in $root/.env cannot be used. $1" >&2
    for problem in "${DW_PORT_PROBLEMS[@]}"; do
        echo "  $problem" >&2
    done
    return 1
}

# Export the directory that holds this machine's resolver configuration,
# and the file's name in it. NetworkManager and systemd-resolved replace the
# file rather than edit it, so the auto-configuration service mounts the
# directory. A symlink, such as into /run/systemd/resolve, is followed.
dw_resolver() {
    local file
    file=$(readlink -f -- "${DAYWARDEN_ETC:-/etc}/resolv.conf" 2>/dev/null) || file=""
    if [ -n "$file" ] && [ -d "$(dirname -- "$file")" ]; then
        export RESOLV_CONF_DIR="${RESOLV_CONF_DIR:-$(dirname -- "$file")}"
        export RESOLV_CONF_NAME="${RESOLV_CONF_NAME:-$(basename -- "$file")}"
    fi
}

dw_machine_hostname() {
    local name=""
    [ -r "${DAYWARDEN_ETC:-/etc}/hostname" ] && name=$(tr -d ' \t\r\n' <"${DAYWARDEN_ETC:-/etc}/hostname")
    [ -n "$name" ] || name=$(uname -n)
    printf '%s\n' "$name"
}

# Print the proxy auto-config URL. The running auto-configuration service
# knows the policy's hostname. Without it, this machine's hostname is used.
dw_config_url() {
    local url=""
    if dw_running autoconfig; then
        url=$(dw_compose exec -T autoconfig python -m policy.autoconfig --url 2>/dev/null) || url=""
    fi
    [ -n "$url" ] || url="http://$(dw_machine_hostname):${PROXY_CONFIG_PORT:-8088}/proxy.pac"
    printf '%s\n' "$url"
}

# Without the default build attestations, rebuilding unchanged source gives
# the same image ID. With them, every build is a new image, so Compose would
# recreate containers that dw restart --keep and dw up mean to keep.
dw_compose() {
    BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose --project-directory "$root" "$@"
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

# Print the container ID of each service that has a container, running or
# stopped, as "service<TAB>id".
dw_container_ids() {
    local service id
    for service in "${DW_SERVICES[@]}"; do
        id=$(dw_compose ps -a -q "$service" 2>/dev/null) || id=""
        [ -n "$id" ] && printf '%s\t%s\n' "$service" "$id"
    done
    return 0
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

# The host directory mounted at /etc/daywarden, written the way the parent
# would from the daywarden directory, such as config.
dw_config_dir() {
    local dir=${DAYWARDEN_CONFIG_DIR:-./config}
    case "$dir" in
    "$root"/*) dir=${dir#"$root"/} ;;
    /*) ;;
    *) dir=${dir#./} ;;
    esac
    printf '%s\n' "$dir"
}

# The config directory as an absolute path, for the config history.
dw_config_path() {
    local dir
    dir=$(dw_config_dir)
    case "$dir" in
    /*) printf '%s\n' "$dir" ;;
    *) printf '%s\n' "$root/$dir" ;;
    esac
}

# The config history: a local git repository in the config directory, with
# no remote. Every git call ignores the user's global and system git
# config, so signing, hooks, templates, and a missing identity never get in
# the way, and nothing is written to them. The author and committer are the
# host user at daywarden.invalid, and the dates are in the household's
# timezone when policy.yaml sets one.
DW_HISTORY_IGNORE='# Written by daywarden. The config history leaves out editor leftovers, and
# the .sample files that every install rewrites.
*~
*.swp
*.swo
.#*
\#*#
*.sample'

dw_household_tz() {
    [ -f "$1/policy.yaml" ] || return 0
    awk '/^timezone:/ {
        value = $0
        sub(/^timezone:[ \t]*/, "", value)
        sub(/[ \t]+#.*$/, "", value)
        gsub(/^["\047]|["\047][ \t]*$/, "", value)
        print value
        exit
    }' "$1/policy.yaml"
}

dw_git() {
    local dir=$1 name zone
    shift
    name=$(dw_user)
    zone=$(dw_household_tz "$dir")
    TZ=${zone:-${TZ:-}} GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
        GIT_AUTHOR_NAME=$name GIT_AUTHOR_EMAIL=$name@daywarden.invalid \
        GIT_COMMITTER_NAME=$name GIT_COMMITTER_EMAIL=$name@daywarden.invalid \
        git -C "$dir" "$@"
}

dw_history_warn() {
    echo "Warning: this change to $(dw_tilde "$1") is not in the config history, because $2" >&2
    [ -z "${3:-}" ] || printf '%s\n' "$3" | sed 's/^/  /' >&2
}

dw_tilde() {
    printf '%s\n' "${1/#"$HOME"/\~}"
}

# Commit every uncommitted change in the config directory's own repository,
# with the time, the host user, and the command as the message, such as
# "2026-11-08 21:15 -0500 blg: dw reload". Does nothing without a repository
# of its own. A failure is a warning, so what ran still counts.
dw_history_commit() {
    local dir=$1 command=$2 out zone stamp files=() names waited=0
    [ -e "$dir/.git" ] || return 0
    if ! command -v git >/dev/null 2>&1; then
        dw_history_warn "$dir" "git is not installed. Fix: sudo pacman -S git"
        return 0
    fi
    while [ -e "$dir/.git/index.lock" ] && [ "$waited" -lt 50 ]; do
        sleep 0.1
        waited=$((waited + 1))
    done
    if ! out=$(dw_git "$dir" add --all 2>&1); then
        dw_history_warn "$dir" "git could not add it:" "$out"
        return 0
    fi
    dw_git "$dir" diff --cached --quiet 2>/dev/null && return 0
    mapfile -t files < <(dw_git "$dir" -c core.quotePath=false diff --cached --name-only 2>/dev/null)
    zone=$(dw_household_tz "$dir")
    stamp=$(TZ=${zone:-${TZ:-}} date '+%Y-%m-%d %H:%M %z')
    if ! out=$(dw_git "$dir" commit --quiet -m "$stamp $(dw_user): $command" 2>&1); then
        dw_history_warn "$dir" "git could not commit it:" "$out"
        return 0
    fi
    printf -v names '%s, ' "${files[@]}"
    echo "Saved in the config history: ${names%, }."
}

# Create the config history when the config directory has none, with what
# is there as the first version. A directory inside another git work tree,
# such as config/ in a clone of the daywarden repository, gets none: the
# outer repository is its history. With a history already there, commit any
# uncommitted change instead.
dw_history_keep() {
    local dir=$1 command=$2 out
    [ -d "$dir" ] || return 0
    if [ -e "$dir/.git" ]; then
        dw_history_commit "$dir" "$command"
        return 0
    fi
    if ! command -v git >/dev/null 2>&1; then
        echo "Warning: git is not installed, so $(dw_tilde "$dir") has no config history. Fix: sudo pacman -S git" >&2
        return 0
    fi
    if [ "$(dw_git "$dir" rev-parse --is-inside-work-tree 2>/dev/null)" = true ]; then
        echo "$(dw_tilde "$dir") is inside the git repository $(dw_tilde "$(dw_git "$dir" rev-parse --show-toplevel)"), which is its history, so it gets no config history of its own."
        return 0
    fi
    [ -e "$dir/.gitignore" ] || printf '%s\n' "$DW_HISTORY_IGNORE" >"$dir/.gitignore"
    if ! out=$(dw_git "$dir" init --quiet --initial-branch=main 2>&1); then
        echo "Warning: the config history could not be created in $(dw_tilde "$dir"), because git init failed:" >&2
        printf '%s\n' "$out" | sed 's/^/  /' >&2
        return 0
    fi
    echo "Started the config history in $(dw_tilde "$dir"). See its history with git log there."
    dw_history_commit "$dir" "$command" >/dev/null
}

# Create the CA and data directories, so Docker does not create them owned
# by root.
dw_make_dirs() {
    if [ -z "${CA_VOLUME_PATH:-}" ]; then
        echo "dw: CA_VOLUME_PATH is not set in $root/.env." >&2
        return 1
    fi
    mkdir -p -- "$CA_VOLUME_PATH" "$(dw_data_dir)"
}

# Check the policy with the code in the policy image, and change nothing.
# The first argument is exec, for the running decisions container, or run,
# for a new container that starts no other service and publishes no port.
# The rest go to policy.check. PARENT_NAMES from .env goes too, so the check
# warns about a policy-server name bypass.txt does not match, even while the
# running container still has the old value. True when the policy has no errors.
dw_check_policy() {
    local how=$1
    shift
    local check=(python -m policy.check --host-dir "$(dw_config_dir)" --parent-names "${PARENT_NAMES:-}" "$@")
    if [ "$how" = exec ]; then
        dw_compose exec -T decisions "${check[@]}"
        return
    fi
    dw_make_dirs || return 1
    dw_compose --progress quiet run --rm --no-deps -T --quiet-build decisions "${check[@]}"
}

# Check the policy, then start the stack and wait until every service is
# healthy. The argument ends the count line when the policy has errors,
# such as "daywarden was not started.".
dw_compose_up() {
    dw_require_ports "$1" || return 1
    dw_make_dirs || return 1
    dw_check_policy run --quiet --refused "$1" || return 1
    dw_start_checked
}

# Start the stack once the policy has been checked, and wait until every
# service is healthy. Name each service that is not, and show why. Any
# arguments go to docker compose up.
dw_start_checked() {
    local bad="" service state failed=()
    dw_make_dirs || return 1
    if dw_compose up -d --wait --wait-timeout 180 "$@"; then
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

# Print each running service whose container was created from settings
# other than .env and docker-compose.yml give now. Compose labels each
# container with the hash of the settings it was created from.
dw_stale_services() {
    local wanted service hash
    local -A want=()
    wanted=$(dw_compose config --hash '*' 2>/dev/null) || return 0
    while read -r service hash; do
        [ -n "$service" ] && want[$service]=$hash
    done <<<"$wanted"
    while IFS=$'\t' read -r service hash; do
        [ -n "$service" ] || continue
        [ "${want[$service]:-}" = "$hash" ] || printf '%s\n' "$service"
    done < <(docker ps --filter "label=com.docker.compose.project=${DW_PROJECT:-daywarden}" \
        --format '{{.Label "com.docker.compose.service"}}	{{.Label "com.docker.compose.config-hash"}}' 2>/dev/null | sort)
}

# While daywarden starts at boot, start the user service too, so it shows
# active and dw down stops it.
dw_track_with_user_service() {
    if dw_user_manager && dw_enabled; then
        if ! systemctl --user start "$DW_UNIT"; then
            echo "dw: the daywarden user service did not start. See dw logs boot." >&2
            return 1
        fi
    fi
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
