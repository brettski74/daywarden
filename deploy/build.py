"""Build dist/daywarden-<version>.tar.gz: make dist.

The version is the local build time, YYYYMMDD-HHMMSS. The policy and proxy
images are built, tagged with it, and saved into the package, so the target
machine never builds or pulls a daywarden image. The tarball unpacks to one
directory, daywarden-<version>/, holding:

    install.sh            installs or upgrades ~/daywarden for this user
    VERSION, ARCH         the version, and the CPU architecture of the images
    images.tar            both images, for docker load
    docker-compose.yml    the repository's compose file, set to those images
    env.sample            the repository's .env, with paths under ~/daywarden, the
                          default ports, and a stand-in policy server name
    config/               the repository's policy.yaml and bypass.txt, the YAML
                          files in its tasks.d/, which policy.yaml includes, and
                          the pools in its parts_of_speech_pools/ and
                          capitalisation_pools/

The repository's .env and bypass.txt are this machine's development settings.
The package never carries them: its ports are the defaults, and its policy
server is SAMPLE_SERVER, which install.sh replaces with the installing
machine's names.
    bin/                  the host commands
    lib/policy/           the Python source cut-clips runs, with requirements.txt,
                          and not the parent portal, which is built into the image

The repository's .env, compose file, and make up are not changed.

Run with: python -m deploy.build [--out DIR]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY_IMAGE = "daywarden-policy"
PROXY_IMAGE = "daywarden-proxy"
COMMANDS = ("dw", "rm-attempts", "word-stats", "add-parent", "cut-clips", "daywarden-service", "daywarden-lib.sh")
DEV_DATA_DIR = "${DAYWARDEN_DATA_DIR:-${HOME}/daywarden}"
SAMPLE_ENV = {
    "CA_VOLUME_PATH": "${HOME}/daywarden/ca",
    "DAYWARDEN_DATA_DIR": "${HOME}/daywarden/data",
}
# The policy server's name in the package. install.sh replaces it with this machine's names.
SAMPLE_SERVER = "daywarden-server"
# Set in the package whatever the development .env says.
SAMPLE_DEFAULTS = {"PORT_BASE": "8080", "PARENT_NAMES": f"{SAMPLE_SERVER},localhost,127.0.0.1"}
# A port set on its own wins over PORT_BASE, so the package sets none.
SINGLE_PORTS = ("PROXY_PORT", "POLICY_PORT", "PROXY_CONFIG_PORT")
POOLS_DIRS = ("parts_of_speech_pools", "capitalisation_pools")
COMPOSE_HEADER = """\
# daywarden {version}. install.sh replaces this file on every upgrade.
# Change .env and config/ instead. Start with: dw up
# Built by make dist from the repository's docker-compose.yml. The images
# are loaded from the package, so nothing here is built or pulled.
# on-failure brings back a container that crashes. Docker does not start
# these containers by itself when it starts: each one exits 0 when Docker
# stops it. Whether daywarden runs after a boot is up to dw enable.
"""


def installed_compose(text: str, version: str) -> str:
    """Return the repository's compose file, set to run the packaged images."""
    document = yaml.safe_load(text)
    services = document["services"]
    for service in services.values():
        service.pop("build", None)
        if str(service.get("image", "")).startswith(f"{POLICY_IMAGE}:"):
            service["image"] = f"{POLICY_IMAGE}:{version}"
        service["pull_policy"] = "never"
        service["restart"] = "on-failure"
    proxy = services["proxy"]
    proxy["image"] = f"{PROXY_IMAGE}:{version}"
    proxy["volumes"] = [volume for volume in proxy["volumes"] if not str(volume).startswith("./proxy:")]
    data = [
        volume
        for volume in services["decisions"]["volumes"]
        if isinstance(volume, dict) and volume.get("source") == DEV_DATA_DIR
    ]
    if len(data) != 1:
        raise ValueError(f"the decisions service does not mount {DEV_DATA_DIR}")
    data[0]["source"] = "${DAYWARDEN_DATA_DIR:-${HOME}/daywarden/data}"
    body = yaml.safe_dump(document, sort_keys=False, default_flow_style=False, width=1000)
    return COMPOSE_HEADER.format(version=version) + "\n" + body


def proxy_base_image(text: str) -> str:
    """Return the mitmproxy image the development stack runs."""
    return yaml.safe_load(text)["services"]["proxy"]["image"]


def sample_env(text: str) -> str:
    """Return the repository's .env as the package's sample.

    The CA and data directories go under ~/daywarden. PORT_BASE is the default
    and PARENT_NAMES names SAMPLE_SERVER, whatever this machine's .env says, and
    a port set on its own is left out, so the sample is the same on every
    build machine. The comments are kept.
    """
    lines = [line for line in text.splitlines() if not line.startswith(tuple(f"{key}=" for key in SINGLE_PORTS))]
    for key, value in SAMPLE_ENV.items():
        found = [index for index, line in enumerate(lines) if line.startswith(f"{key}=")]
        if not found:
            raise ValueError(f".env does not set {key}")
        for index in found:
            lines[index] = f"{key}={value}"
    for key, value in SAMPLE_DEFAULTS.items():
        found = [index for index, line in enumerate(lines) if line.startswith(f"{key}=")]
        for index in found:
            lines[index] = f"{key}={value}"
        if not found:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def sample_bypass(text: str, parent_names: str) -> str:
    """Return the repository's bypass.txt with this machine's policy server names as SAMPLE_SERVER.

    A server line is one in the block under a ``# Policy server`` comment, or
    one that names a PARENT_NAMES entry of this machine's .env. The first
    becomes SAMPLE_SERVER and the rest are dropped, so install.sh finds the one
    line it replaces with the installing machine's names.
    """
    names = {name.strip().lower() for name in parent_names.split(",")} - {"", "localhost", "127.0.0.1", "::1"}
    out: list[str] = []
    in_block = False
    placed = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("# policy server"):
            in_block = True
        elif not stripped:
            in_block = False
        server = bool(stripped) and not stripped.startswith("#") and (in_block or stripped.lower() in names)
        if server:
            if not placed:
                out.append(SAMPLE_SERVER)
                placed = True
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def env_value(text: str, key: str) -> str:
    found = [line.split("=", 1)[1] for line in text.splitlines() if line.startswith(f"{key}=")]
    return found[-1] if found else ""


def _run(*command: str) -> str:
    print("+", " ".join(command), flush=True)
    done = subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True)
    return done.stdout


def _copy_policy(destination: Path) -> None:
    shutil.copytree(
        ROOT / "policy",
        destination,
        # cut-clips needs only the Python. The portal is built into the image.
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "Dockerfile", ".dockerignore", "portal"),
    )


def stage(package: Path, version: str, arch: str) -> None:
    """Write every file of the package into ``package`` except images.tar."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    (package / "bin").mkdir(parents=True)
    (package / "config").mkdir()
    (package / "lib").mkdir()
    shutil.copy2(ROOT / "deploy" / "install.sh", package / "install.sh")
    for command in COMMANDS:
        shutil.copy2(ROOT / "bin" / command, package / "bin" / command)
    env = (ROOT / ".env").read_text(encoding="utf-8")
    shutil.copy2(ROOT / "config" / "policy.yaml", package / "config" / "policy.yaml")
    bypass = sample_bypass((ROOT / "config" / "bypass.txt").read_text(encoding="utf-8"), env_value(env, "PARENT_NAMES"))
    (package / "config" / "bypass.txt").write_text(bypass, encoding="utf-8")
    tasks = sorted(path for path in (ROOT / "config" / "tasks.d").glob("*") if path.suffix in (".yaml", ".yml") and path.is_file())
    if tasks:
        (package / "config" / "tasks.d").mkdir()
        for path in tasks:
            shutil.copy2(path, package / "config" / "tasks.d" / path.name)
    for folder in POOLS_DIRS:
        pools = sorted(path for path in (ROOT / "config" / folder).glob("*") if path.suffix in (".yaml", ".yml") and path.is_file())
        if pools:
            (package / "config" / folder).mkdir()
            for path in pools:
                shutil.copy2(path, package / "config" / folder / path.name)
    _copy_policy(package / "lib" / "policy")
    (package / "docker-compose.yml").write_text(installed_compose(compose, version), encoding="utf-8")
    (package / "env.sample").write_text(sample_env(env), encoding="utf-8")
    (package / "VERSION").write_text(version + "\n", encoding="utf-8")
    (package / "ARCH").write_text(arch + "\n", encoding="utf-8")


def build(out: Path, version: str, *, compresslevel: int = 6) -> Path:
    """Build the images and the package. Return the tarball's path."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    policy_tag, proxy_tag = f"{POLICY_IMAGE}:{version}", f"{PROXY_IMAGE}:{version}"
    _run("docker", "build", "--tag", policy_tag, "policy")
    _run("docker", "build", "--tag", proxy_tag, "--build-arg", f"MITMPROXY_IMAGE={proxy_base_image(compose)}", "proxy")
    arches = {_run("docker", "image", "inspect", "--format", "{{.Architecture}}", tag).strip() for tag in (policy_tag, proxy_tag)}
    if len(arches) != 1:
        raise SystemExit(f"the images were built for different architectures: {', '.join(sorted(arches))}")
    out.mkdir(parents=True, exist_ok=True)
    name = f"daywarden-{version}"
    tarball = out / f"{name}.tar.gz"
    with tempfile.TemporaryDirectory(dir=out, prefix=".building-") as scratch:
        package = Path(scratch) / name
        stage(package, version, arches.pop())
        _run("docker", "save", "--output", str(package / "images.tar"), policy_tag, proxy_tag)
        print(f"+ writing {tarball}", flush=True)
        partial = Path(scratch) / tarball.name
        with tarfile.open(partial, "w:gz", compresslevel=compresslevel) as archive:
            archive.add(package, arcname=name)
        partial.replace(tarball)
    return tarball


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make dist", description="Build the daywarden install package.")
    parser.add_argument("--out", type=Path, default=ROOT / "dist", help="where the tarball is written (default dist/)")
    parser.add_argument("--version", default=None, help="the version, by default the build time YYYYMMDD-HHMMSS")
    args = parser.parse_args(argv)
    version = args.version or datetime.now().strftime("%Y%m%d-%H%M%S")
    tarball = build(args.out.resolve(), version)
    print(f"Built {tarball}")
    print(f"Copy it to the target, then: tar -xzf {tarball.name} && cd daywarden-{version} && ./install.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
