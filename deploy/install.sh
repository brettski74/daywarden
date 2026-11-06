#!/usr/bin/env bash
# Install or upgrade daywarden for the user who runs it, from the unpacked
# package made by make dist:
#   ./install.sh
# Everything goes under ~/daywarden. dw, rm-attempts, add-parent, and
# cut-clips are linked into ~/bin. Every dependency is checked first, and
# nothing changes when a required one is missing. .env, config/policy.yaml,
# and config/bypass.txt are created only when missing and never overwritten.
# The package's copies are always installed beside them as .sample files.
set -euo pipefail

package=$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")
root="$HOME/daywarden"
bindir="$HOME/bin"
etc=${DAYWARDEN_ETC:-/etc}
LINKED=(dw rm-attempts add-parent cut-clips)
# shellcheck source=../bin/daywarden-lib.sh
. "$package/bin/daywarden-lib.sh"

if [ "$(id -u)" -eq 0 ]; then
    echo "install.sh: do not run this as root. It installs for the user who runs it, and for root that is /root." >&2
    echo "  Run it as the user who will run daywarden." >&2
    exit 1
fi

version=$(<"$package/VERSION")
problems=()
warnings=()

tilde() {
    printf '%s\n' "${1/#"$HOME"/\~}"
}

problem() {
    problems+=("Problem: $1"$'\n'"  Fix: $2")
}

warning() {
    warnings+=("Warning: $1"$'\n'"  Fix: $2")
}

ask() {
    local answer=""
    printf '%s [y/N] ' "$1"
    if ! read -r answer; then
        echo
    fi
    case "${answer,,}" in
    y | yes) return 0 ;;
    esac
    return 1
}

# Checks

docker_ok=0
check_docker() {
    local err user
    user=$(dw_user)
    if ! command -v docker >/dev/null 2>&1; then
        problem "docker is not installed." "sudo pacman -S docker"
        problem "docker compose (the Compose v2 plugin) is not installed." "sudo pacman -S docker-compose"
        return
    fi
    if ! docker compose version >/dev/null 2>&1; then
        problem "docker compose (the Compose v2 plugin) is not installed." "sudo pacman -S docker-compose"
    fi
    if err=$(timeout 20 docker info 2>&1 >/dev/null); then
        docker_ok=1
    elif [[ ${err,,} == *"permission denied"* ]]; then
        problem "This user cannot reach the Docker daemon without sudo." \
            "sudo usermod -aG docker $user, then log out and back in"
    else
        problem "The Docker daemon is not running, or this user cannot reach it." \
            "sudo systemctl enable --now docker.service, or sudo usermod -aG docker $user, then log out and back in"
    fi
}

machine_arch() {
    case "$(uname -m)" in
    x86_64 | amd64) echo amd64 ;;
    aarch64 | arm64) echo arm64 ;;
    armv6* | armv7* | armhf) echo arm ;;
    i?86) echo 386 ;;
    *) uname -m ;;
    esac
}

check_package() {
    local file built here
    for file in VERSION ARCH images.tar docker-compose.yml env.sample config/policy.yaml config/bypass.txt lib/policy/requirements.txt; do
        if [ ! -e "$package/$file" ]; then
            problem "The package in $package is incomplete: $file is missing." "unpack the tarball again, or build a new one with make dist"
        fi
    done
    [ -f "$package/ARCH" ] || return 0
    built=$(<"$package/ARCH")
    here=$(machine_arch)
    if [ "$built" != "$here" ]; then
        problem "This package's images were built for $built, but this machine is $here ($(uname -m))." \
            "build the package with make dist on a $here machine"
    fi
}

ours() {
    [ -L "$1" ] && [ "$(readlink -- "$1")" = "$root/bin/$2" ]
}

check_bin() {
    local name path
    for name in "${LINKED[@]}"; do
        path="$bindir/$name"
        if { [ -e "$path" ] || [ -L "$path" ]; } && ! ours "$path" "$name"; then
            problem "$(tilde "$path") is already there, and daywarden did not install it." \
                "move or rename it, then run install.sh again"
        fi
    done
}

env_file() {
    if [ -f "$root/.env" ]; then
        echo "$root/.env"
    else
        echo "$package/env.sample"
    fi
}

check_ports() {
    local listening published key port
    command -v ss >/dev/null 2>&1 || return 0
    listening=$(ss -Hltn 2>/dev/null | awk '{ print $4 }') || return 0
    published=""
    if [ "$docker_ok" -eq 1 ]; then
        published=$(docker ps --filter "label=com.docker.compose.project=$DW_PROJECT" --format '{{.Ports}}' 2>/dev/null || true)
    fi
    while read -r key port; do
        [ -n "$port" ] || continue
        if grep -qE "[:.]$port\$" <<<"$listening" && [[ $published != *":$port->"* ]]; then
            warning "Port $port ($key) is already in use by another program, so dw up would fail." \
                "stop that program, or change $key in ~/daywarden/.env before dw up"
        fi
    done < <(
        dw_load_env "$(env_file)"
        printf 'PROXY_PORT %s\nPOLICY_PORT %s\n' "${PROXY_PORT:-}" "${POLICY_PORT:-8090}"
    )
}

check_path() {
    case ":$PATH:" in
    *":$bindir:"* | *":$bindir/:"*) ;;
    *)
        # shellcheck disable=SC2016
        warning "~/bin is not on the PATH, so dw and the other commands are not found by name." \
            'add this line to ~/.bashrc, then open a new terminal: export PATH="$HOME/bin:$PATH"'
        ;;
    esac
}

have_python=0
check_cut_clips() {
    local encoders=""
    if command -v python3 >/dev/null 2>&1; then
        have_python=1
    else
        warning "python3 is not installed, so cut-clips will not work." "sudo pacman -S python, then run install.sh again"
    fi
    if command -v ffmpeg >/dev/null 2>&1; then
        encoders=$(ffmpeg -hide_banner -encoders 2>/dev/null || true)
    fi
    if ! grep -qE '^ *A[^ ]* +libopus ' <<<"$encoders"; then
        warning "ffmpeg is not installed, or cannot encode Opus (libopus), so cut-clips will not work." \
            "sudo pacman -S ffmpeg. ffplay, which cut-clips --play uses, comes with it"
    fi
}

user_manager=0
check_systemd() {
    if ! dw_docker_starts_at_boot; then
        warning "Neither docker.service nor docker.socket is enabled at boot, so daywarden cannot start at boot." \
            "sudo systemctl enable docker.service"
    fi
    if dw_user_manager; then
        user_manager=1
    else
        warning "This user's systemd manager cannot be reached with systemctl --user, for example in a su session with no user runtime directory. dw enable will not work until it can." \
            "log in as $(dw_user) directly, such as over ssh, and run dw enable"
    fi
}

# Names for this machine

added_names=()
skipped_names=()

machine_hostname() {
    local name=""
    if [ -r "$etc/hostname" ]; then
        name=$(tr -d ' \t\r\n' <"$etc/hostname")
    fi
    [ -n "$name" ] || name=$(uname -n)
    printf '%s\n' "$name"
}

search_suffixes() {
    [ -r "$etc/resolv.conf" ] || return 0
    awk '$1 == "search" || $1 == "domain" { for (i = 2; i <= NF; i++) print $i }' "$etc/resolv.conf"
}

local_addresses() {
    ip -o addr show 2>/dev/null | awk '$2 != "lo" { sub(/\/.*/, "", $4); print $4 }' || true
}

is_loopback() {
    case "$1" in
    127.* | ::1 | ::ffff:127.*) return 0 ;;
    esac
    return 1
}

joined() {
    local IFS=' '
    local text="$*"
    printf '%s\n' "${text// / and }"
}

# Fill added_names with <host>.<suffix> for each search suffix whose name
# resolves to an address on this machine, and skipped_names with the rest.
qualify() {
    local host=$1 suffix name addresses mine rc address found loopback
    local -A seen=(["${host,,}"]=1)
    mine=$(local_addresses)
    while read -r suffix; do
        suffix=${suffix%.}
        [ -n "$suffix" ] || continue
        name="$host.$suffix"
        [ -z "${seen[${name,,}]:-}" ] || continue
        seen[${name,,}]=1
        rc=0
        addresses=$(timeout 2 getent ahosts "$name" 2>/dev/null | awk '!seen[$1]++ { print $1 }') || rc=$?
        if [ "$rc" -eq 124 ]; then
            skipped_names+=("$name: the lookup took longer than 2 seconds")
            continue
        fi
        if [ -z "$addresses" ]; then
            skipped_names+=("$name: does not resolve")
            continue
        fi
        found=0
        loopback=1
        for address in $addresses; do
            is_loopback "$address" || loopback=0
            if grep -qxF -- "$address" <<<"$mine"; then
                found=1
            fi
        done
        if [ "$found" -eq 1 ]; then
            added_names+=("$name")
        elif [ "$loopback" -eq 1 ]; then
            # shellcheck disable=SC2086
            skipped_names+=("$name: resolves only to loopback ($(joined $addresses))")
        else
            # shellcheck disable=SC2086
            skipped_names+=("$name: resolves to $(joined $addresses), not this machine")
        fi
    done < <(search_suffixes)
}

# PARENT_NAMES in the sample .env becomes this machine's names.
substitute_env() {
    NAMES="$parent_names" awk '
        /^PARENT_NAMES=/ { if (!done) print "PARENT_NAMES=" ENVIRON["NAMES"]; done = 1; next }
        { print }
        END { if (!done) print "PARENT_NAMES=" ENVIRON["NAMES"] }
    ' "$package/env.sample" >"$1"
}

# A bypass.txt line naming the build machine, one of the PARENT_NAMES in the
# package, is a policy-server line. The first becomes this machine's names.
substitute_bypass() {
    local old
    old=$(sed -n 's/^PARENT_NAMES=//p' "$package/env.sample")
    OLD="$old" NEW="$server_names" awk '
        function trim(text) { gsub(/^[ \t]+|[ \t]+$/, "", text); return text }
        BEGIN {
            count = split(tolower(ENVIRON["OLD"]), list, ",")
            for (i = 1; i <= count; i++) {
                name = trim(list[i])
                if (name != "" && name != "localhost" && name != "127.0.0.1" && name != "::1") server[name] = 1
            }
            lines = split(ENVIRON["NEW"], replacement, ",")
        }
        {
            line = tolower(trim($0))
            if (line !~ /^#/ && (line in server)) {
                if (!done) for (i = 1; i <= lines; i++) print replacement[i]
                done = 1
                next
            }
            print
        }
        END {
            if (!done) {
                print ""
                print "# Policy server."
                for (i = 1; i <= lines; i++) print replacement[i]
            }
        }
    ' "$package/config/bypass.txt" >"$1"
}

# Installing

created=()
kept=()

install_file() {
    cp -- "$1" "$2.new"
    chmod "$3" "$2.new"
    mv -f -- "$2.new" "$2"
}

replace_dir() {
    rm -rf -- "$2.new"
    cp -R -- "$1" "$2.new"
    rm -rf -- "$2"
    mv -- "$2.new" "$2"
}

keep_or_create() {
    if [ -e "$2" ]; then
        kept+=("$(tilde "$2")")
    else
        cp -- "$1" "$2"
        created+=("$(tilde "$2")")
    fi
}

# Build venv/ for cut-clips, unless it was built from these requirements
# with this Python version.
build_venv() {
    local venv="$root/venv" requirements="$root/lib/policy/requirements.txt" want log
    if [ "$have_python" -eq 0 ]; then
        echo "Skipped the cut-clips environment: python3 is not installed."
        return 0
    fi
    want="python $(python3 -c 'import platform; print(platform.python_version())' 2>/dev/null || echo unknown)
requirements $(sha256sum <"$requirements" | cut -d ' ' -f 1)"
    if [ -x "$venv/bin/python" ] && [ -f "$venv/.daywarden-build" ] && [ "$(<"$venv/.daywarden-build")" = "$want" ]; then
        echo "The cut-clips environment in ~/daywarden/venv is up to date."
        return 0
    fi
    echo "Building the cut-clips environment in ~/daywarden/venv. This downloads packages from PyPI..."
    log=$(mktemp)
    rm -rf -- "$venv"
    if python3 -m venv "$venv" >"$log" 2>&1 &&
        "$venv/bin/python" -m pip install --disable-pip-version-check --quiet -r "$requirements" >>"$log" 2>&1; then
        printf '%s\n' "$want" >"$venv/.daywarden-build"
        rm -f -- "$log"
        echo "Built the cut-clips environment."
        return 0
    fi
    echo "Building the cut-clips environment failed. The last lines it printed:" >&2
    tail -n 15 "$log" | sed 's/^/  /' >&2
    rm -f -- "$log"
    rm -rf -- "$venv"
    warning "The cut-clips environment could not be built, so cut-clips will not work. Everything else is installed." \
        "fix the problem above, such as the network connection to PyPI, then run install.sh again"
}

print_list() {
    local item
    for item in "$@"; do
        printf '%s\n' "$item"
    done
}

# Main

check_package
check_docker
check_bin
DW_PROJECT=$(
    dw_load_env "$(env_file)" 2>/dev/null || true
    echo "${COMPOSE_PROJECT_NAME:-daywarden}"
)
check_systemd
check_ports
check_path
check_cut_clips

if [ ${#problems[@]} -gt 0 ]; then
    {
        print_list "${problems[@]}"
        [ ${#warnings[@]} -eq 0 ] || print_list "${warnings[@]}"
        echo "install.sh: nothing was changed. Fix the problems above, then run install.sh again."
    } >&2
    exit 1
fi
[ ${#warnings[@]} -eq 0 ] || print_list "${warnings[@]}"

first_install=1
[ -f "$root/VERSION" ] && first_install=0
running=0
if dw_running; then
    running=1
    if ! ask "Daywarden is running. Restart it to finish the upgrade?"; then
        echo "install.sh: the upgrade was stopped. Nothing was changed, and daywarden is still running." >&2
        exit 1
    fi
fi

host=$(machine_hostname)
qualify "$host"
server_names=$(
    IFS=,
    echo "${host},${added_names[*]}"
)
server_names=${server_names%,}
parent_names="$server_names,localhost,127.0.0.1"

echo "Loading the images..."
docker load --input "$package/images.tar"

scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
substitute_env "$scratch/env"
substitute_bypass "$scratch/bypass.txt"

mkdir -p -- "$root/config" "$root/ca" "$root/data" "$bindir"
install_file "$package/docker-compose.yml" "$root/docker-compose.yml" 644
install_file "$scratch/env" "$root/.env.sample" 644
keep_or_create "$root/.env.sample" "$root/.env"
install_file "$package/config/policy.yaml" "$root/config/policy.yaml.sample" 644
keep_or_create "$root/config/policy.yaml.sample" "$root/config/policy.yaml"
install_file "$scratch/bypass.txt" "$root/config/bypass.txt.sample" 644
keep_or_create "$root/config/bypass.txt.sample" "$root/config/bypass.txt"
replace_dir "$package/lib" "$root/lib"
replace_dir "$package/bin" "$root/bin"
for name in "${LINKED[@]}"; do
    ln -sfn -- "$root/bin/$name" "$bindir/$name"
done
install_file "$package/VERSION" "$root/VERSION" 644

build_venv

if [ "$user_manager" -eq 1 ] && dw_enabled; then
    dw_write_unit || true
    systemctl --user daemon-reload
    echo "daywarden starts at boot. Rewrote $(tilde "$(dw_unit_path)") from this package."
fi

status=0
restarted=""
if [ "$running" -eq 1 ]; then
    echo "Restarting daywarden..."
    "$root/bin/dw" down
    if "$root/bin/dw" up; then
        restarted="daywarden restarted on $version, and every service is healthy."
    else
        restarted="daywarden $version is installed, but it did not come back healthy. Fix the configuration in ~/daywarden, then run dw up again."
        status=1
    fi
fi

enabled_now=0
if [ "$first_install" -eq 1 ]; then
    if [ "$user_manager" -eq 1 ]; then
        if ask "Start daywarden automatically at boot?"; then
            if "$root/bin/dw" enable; then
                enabled_now=1
            else
                warning "dw enable failed, so daywarden does not start at boot." "fix the problem above, then run dw enable"
            fi
        fi
    else
        echo "Not asking about start at boot:"
        dw_user_manager_advice
    fi
fi

echo
echo "daywarden $version is installed in ~/daywarden."
listed() {
    local IFS=,
    local text="$*"
    printf '%s\n' "${text//,/, }"
}
[ ${#created[@]} -eq 0 ] || echo "Created: $(listed "${created[@]}")"
[ ${#kept[@]} -eq 0 ] || echo "Kept unchanged: $(listed "${kept[@]}"). The package's copies are beside them as .sample files."
echo "Names for this machine in PARENT_NAMES and bypass.txt: ${parent_names//,/, }"
for name in "${added_names[@]}"; do
    echo "  Added $name: it resolves to this machine."
done
for name in "${skipped_names[@]}"; do
    echo "  Skipped $name"
done
[ -z "$restarted" ] || echo "$restarted"
if [ ${#warnings[@]} -gt 0 ]; then
    echo
    print_list "${warnings[@]}"
fi
if [ "$first_install" -eq 1 ]; then
    echo
    echo "Next steps:"
    echo "  - Review ~/daywarden/.env and ~/daywarden/config/policy.yaml."
    echo "  - Add any other names or IP addresses for this machine to PARENT_NAMES in ~/daywarden/.env."
    echo "  - Run dw up, then add a parent with add-parent USERNAME."
    [ "$enabled_now" -eq 1 ] || echo "  - Run dw enable to start daywarden at boot."
    echo "  - Copy ~/daywarden/ca/mitmproxy-ca-cert.pem to the child computers. The first dw up creates it."
fi
exit "$status"
