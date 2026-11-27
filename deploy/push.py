"""Install a package from dist/ on a named environment: make deploy.

The environments are in deploy/environments.ini, which git ignores. The
package is copied with scp to the environment user's home, unpacked to
~/daywarden-<version>/, and installed with its install.sh over ssh, at a
terminal. After a successful install, old versions are removed.

Run with: python -m deploy.push [--env NAME] [--version VERSION]
"""

from __future__ import annotations

import argparse
import configparser
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from deploy.build import POLICY_IMAGE, PROXY_IMAGE

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = "settings"
SETTINGS_KEYS = ("default", "user")
ENVIRONMENT_KEYS = ("host", "user", "port", "keep")
DEFAULT_KEEP = 3
VERSION = r"\d{8}-\d{6}"
PACKAGE = re.compile(rf"daywarden-({VERSION})\.tar\.gz")
DIRECTORY = re.compile(rf"daywarden-({VERSION})")
# Written into a version's directory once it is completely unpacked.
UNPACKED = ".unpacked"


class DeployError(Exception):
    def __init__(self, message: str, status: int = 1):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Environment:
    name: str
    host: str
    user: str | None
    port: int | None
    keep: int

    @property
    def destination(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host


def say(message: str) -> None:
    # Flushed so it stays in order with what ssh and scp print.
    print(message, flush=True)


# The environments file


def load_environment(path: Path, name: str) -> Environment:
    """Return the environment ``name``, or the default one when ``name`` is empty."""
    if not path.is_file():
        raise DeployError(f"{path} is missing. Copy {path.name}.sample to {path.name} and set your machines in it.")
    parser = configparser.ConfigParser(interpolation=None, default_section="")
    try:
        parser.read_string(path.read_text(encoding="utf-8"), source=str(path))
    except configparser.Error as error:
        raise DeployError(f"{path} cannot be read: {error}") from None
    for section in parser.sections():
        known = SETTINGS_KEYS if section == SETTINGS else ENVIRONMENT_KEYS
        for key in parser[section]:
            if key not in known:
                raise DeployError(f"{path}: [{section}] has an unknown setting, {key}. It takes {', '.join(known)}.")
    settings = parser[SETTINGS] if parser.has_section(SETTINGS) else {}
    names = [section for section in parser.sections() if section != SETTINGS]
    configured = f"The environments in {path} are: {', '.join(names)}." if names else f"{path} has no environments."
    name = name or settings.get("default", "")
    if not name:
        raise DeployError(f"No ENV was given, and [{SETTINGS}] sets no default. {configured}")
    if name not in names:
        raise DeployError(f"There is no environment named {name}. {configured}")
    section = parser[name]

    def number(key: str, highest: int | None = None) -> int | None:
        text = section.get(key, "")
        if not text:
            return None
        if not re.fullmatch(r"[0-9]+", text) or int(text) < 1 or (highest and int(text) > highest):
            limit = f"from 1 to {highest}" if highest else "of at least 1"
            raise DeployError(f"{path}: [{name}] {key} must be a whole number {limit}, not {text}.")
        return int(text)

    host = section.get("host", "")
    if not host:
        raise DeployError(f"{path}: [{name}] has no host.")
    user = section.get("user", "") or settings.get("user", "") or None
    for key, value in (("host", host), ("user", user)):
        if value and (value.startswith("-") or "@" in value or any(char.isspace() for char in value)):
            raise DeployError(f"{path}: [{name}] {key} is not a {key} name: {value}")
    return Environment(name, host, user, number("port", 65535), number("keep") or DEFAULT_KEEP)


# The package


def choose_package(dist: Path, version: str) -> tuple[str, Path]:
    """Return the version and path of the newest package, or of ``version``."""
    packages = {}
    if dist.is_dir():
        for path in dist.iterdir():
            match = PACKAGE.fullmatch(path.name)
            if match and path.is_file():
                packages[match[1]] = path
    if not packages:
        raise DeployError(f"There is no package in {dist}. Build one with make dist.")
    version = version or max(packages)
    if version not in packages:
        raise DeployError(f"There is no package for version {version} in {dist}. It has: {', '.join(sorted(packages))}.")
    return version, packages[version]


def age(version: str, now: datetime) -> str:
    """How long ago the version, a local build time, was built."""
    try:
        built = datetime.strptime(version, "%Y%m%d-%H%M%S")
    except ValueError:
        return "at an unknown time"
    seconds = int((now - built).total_seconds())
    for length, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        count = seconds // length
        if count >= 1:
            return f"{count} {unit}{'' if count == 1 else 's'} ago"
    return "just now"


# The environment's machine


class Remote:
    """One shared ssh connection, so a password is asked for only once."""

    def __init__(self, environment: Environment):
        self.environment = environment

    def __enter__(self) -> Remote:
        self._scratch = tempfile.TemporaryDirectory(prefix="dw-ssh-")
        self._options = ["-o", f"ControlPath={self._scratch.name}/s"]
        if self.environment.port:
            self._options += ["-o", f"Port={self.environment.port}"]
        # -f returns once signed in, and leaves the connection open behind it.
        status = self._call(["ssh", *self._options, "-M", "-N", "-f", self.environment.destination])
        if status:
            self._scratch.cleanup()
            raise DeployError(f"Could not connect to {self.environment.destination}.", status)
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            subprocess.run(
                ["ssh", *self._options, "-O", "exit", self.environment.destination],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        finally:
            self._scratch.cleanup()

    def _call(self, command: list[str]) -> int:
        try:
            return subprocess.call(command)
        except FileNotFoundError:
            raise DeployError(f"{command[0]} is not installed on this machine.") from None

    def _ssh(self, script: str, *flags: str) -> list[str]:
        # The user's login shell reads the command, so sh is named for the script.
        return ["ssh", *self._options, *flags, self.environment.destination, f"sh -c {shlex.quote(script)}"]

    def run(self, script: str, *, terminal: bool = False) -> int:
        return self._call(self._ssh(script, *(["-t"] if terminal else [])))

    def output(self, script: str) -> str:
        result = subprocess.run(self._ssh(script), stdout=subprocess.PIPE, text=True)
        if result.returncode:
            raise DeployError(f"A command on {self.environment.destination} failed.", result.returncode)
        return result.stdout

    def copy(self, source: Path, name: str) -> None:
        """Copy ``source`` to ``name`` in the user's home."""
        host = f"[{self.environment.host}]" if ":" in self.environment.host else self.environment.host
        destination = f"{self.environment.user}@{host}" if self.environment.user else host
        status = self._call(["scp", *self._options, str(source), f"{destination}:{name}"])
        if status:
            raise DeployError(f"Copying {source.name} failed.", status)


# The scripts below are run by sh in the user's home. Every name in them is
# made from a version that matched VERSION.


def upload(remote: Remote, version: str, package: Path) -> None:
    """Make ~/daywarden-<version>/, unless a complete one is already there."""
    name = f"daywarden-{version}"
    found = remote.output(f"cd && if [ -f {name}/{UNPACKED} ]; then echo unpacked; elif [ -e {name} ]; then echo partial; fi").strip()
    if found == "unpacked":
        say(f"~/{name} is already there. Installing from it.")
        return
    if found == "partial":
        say(f"~/{name} was not completely unpacked by a deploy. Replacing it.")
    say(f"Copying {package.name}...")
    remote.copy(package, f"{name}.tar.gz")
    say(f"Unpacking to ~/{name}...")
    # Unpacked beside its place and moved there only when whole.
    staging = f".{name}.unpacking"
    status = remote.run(
        f"set -e; cd; trap \"rm -rf {staging}\" EXIT; rm -rf {staging}; mkdir {staging}; "
        f"tar -xzf {name}.tar.gz -C {staging}; touch {staging}/{name}/{UNPACKED}; "
        f"rm -rf {name}; mv {staging}/{name} {name}; rm -f {name}.tar.gz"
    )
    if status:
        raise DeployError(f"Unpacking {name}.tar.gz failed.", status)


def install(remote: Remote, version: str) -> None:
    say("Running install.sh...")
    # An interactive login shell, so install.sh sees the PATH a login there has.
    status = remote.run(f'exec "${{SHELL:-/bin/sh}}" -lic "cd ~/daywarden-{version} && ./install.sh"', terminal=True)
    if status:
        raise DeployError(f"install.sh did not finish. No old version was removed, and ~/daywarden-{version} is kept.", status)


def outdated(directories: set[str], leftovers: set[str], installed: str, keep: int) -> list[str]:
    """The versions to remove: all but the ``keep`` newest directories and the installed one."""
    kept = set(sorted(directories, reverse=True)[:keep]) | {installed}
    return sorted((directories | leftovers) - kept)


def clean_up(remote: Remote, keep: int) -> None:
    listing = remote.output(
        'cd && for path in daywarden-*; do if [ -d "$path" ] && [ ! -L "$path" ]; then echo "directory $path"; '
        'elif [ -f "$path" ]; then echo "file $path"; fi; done; '
        'if [ -f daywarden/VERSION ]; then echo "installed $(cat daywarden/VERSION)"; fi'
    )
    directories, leftovers, installed = set(), set(), ""
    for line in listing.splitlines():
        kind, _, name = line.partition(" ")
        if kind == "directory" and (match := DIRECTORY.fullmatch(name)):
            directories.add(match[1])
        elif kind == "file" and (match := PACKAGE.fullmatch(name)):
            leftovers.add(match[1])
        elif kind == "installed" and re.fullmatch(VERSION, name):
            installed = name
    if not installed:
        say("Warning: ~/daywarden/VERSION does not name a version, so no old version was removed.")
        return
    for version in outdated(directories, leftovers, installed, keep):
        paths = []
        if version in directories:
            paths.append(f"daywarden-{version}")
        if version in leftovers:
            paths.append(f"daywarden-{version}.tar.gz")
        steps = [
            f'if rm -rf -- {path}; then echo "Removed ~/{path}"; else echo "Warning: could not remove ~/{path}"; fi'
            for path in paths
        ]
        steps += [
            f"if docker image inspect {image} >/dev/null 2>&1; then if docker image rm {image} >/dev/null; "
            f'then echo "Removed image {image}"; else echo "Warning: could not remove image {image}"; fi; fi'
            for image in (f"{POLICY_IMAGE}:{version}", f"{PROXY_IMAGE}:{version}")
        ]
        if remote.run("cd || exit 1; " + "; ".join(steps)):
            say(f"Warning: cleaning up version {version} did not finish.")


def deploy(environment: Environment, version: str, package: Path) -> None:
    say(f"Deploying {version}, built {age(version, datetime.now())}, to {environment.name} ({environment.destination}).")
    with Remote(environment) as remote:
        upload(remote, version, package)
        install(remote, version)
        # The install worked, so a failure from here on does not fail the deploy.
        try:
            clean_up(remote, environment.keep)
        except DeployError as error:
            say(f"Warning: old versions were not cleaned up. {error}")
        say("")
        remote.run('exec "$HOME/daywarden/bin/dw" status')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make deploy", description="Install a daywarden package on an environment.")
    parser.add_argument("--env", default="", help="the environment, by default the one [settings] names")
    parser.add_argument("--version", default="", help="the version, by default the newest in dist/")
    parser.add_argument("--config", type=Path, default=ROOT / "deploy" / "environments.ini", help="the environments file")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist", help="where the packages are (default dist/)")
    args = parser.parse_args(argv)
    try:
        environment = load_environment(args.config, args.env)
        version, package = choose_package(args.dist, args.version)
        deploy(environment, version, package)
    except DeployError as error:
        print(f"deploy: {error}", file=sys.stderr)
        return error.status
    except KeyboardInterrupt:
        print("\ndeploy: interrupted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
