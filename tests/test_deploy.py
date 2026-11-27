"""S048: make deploy, against a stand-in environment.

Fake ``ssh`` and ``scp`` treat a temporary directory as the environment
user's home and run the remote commands there with the real sh and tar. A
fake ``docker`` holds the environment's images.
"""

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from hostfakes import ROOT

OLD = ["20261101-000000", "20261102-000000", "20261103-000000", "20261104-000000"]
NEW = "20261105-184500"

FAKE_SSH = r"""
import json, os, shutil, subprocess, sys
from pathlib import Path

remote = Path(os.environ["FAKE_REMOTE"])
args = sys.argv[1:]
program = Path(sys.argv[0]).name
with open(os.environ["FAKE_CALLS"], "a") as log:
    log.write(json.dumps([program, *args]) + "\n")
words = []
while args:
    arg = args.pop(0)
    if arg in ("-o", "-O"):
        args.pop(0)
        if arg == "-O":
            sys.exit(0)
    elif arg in ("-M", "-N", "-f", "-t"):
        if arg == "-M":
            sys.exit(int(os.environ.get("FAKE_CONNECT", "0")))
    else:
        words.append(arg)
if program == "scp":
    source, target = words
    shutil.copy(source, remote / target.rsplit(":", 1)[1])
    sys.exit(0)
env = {**os.environ, "HOME": str(remote), "SHELL": "/bin/sh"}
sys.exit(subprocess.call(["sh", "-c", words[1]], cwd=remote, env=env))
"""

FAKE_DOCKER = r"""
import os, sys
from pathlib import Path

images = Path(os.environ["FAKE_IMAGES"])
held = images.read_text().split()
command, image = sys.argv[2], sys.argv[3]
if image not in held:
    sys.exit(1)
if command == "rm":
    if image in os.environ.get("FAKE_IN_USE", "").split():
        sys.exit("image is in use")
    images.write_text("\n".join(name for name in held if name != image))
"""

INSTALL = """#!/bin/sh
read -r answer || answer=
echo "$answer" >> "$HOME/answers"
[ "$answer" != n ] || exit 1
mkdir -p "$HOME/daywarden/bin"
cp VERSION "$HOME/daywarden/VERSION"
printf '#!/bin/sh\\necho "status of $(cat "$HOME/daywarden/VERSION")"\\nexit 1\\n' > "$HOME/daywarden/bin/dw"
chmod +x "$HOME/daywarden/bin/dw"
"""


class Deployment:
    def __init__(self, root: Path):
        self.remote = root / "remote"
        self.dist = root / "dist"
        self.config = root / "environments.ini"
        self.images = root / "images"
        self.calls_log = root / "calls"
        self.bin = root / "bin"
        for directory in (self.remote, self.dist, self.bin):
            directory.mkdir()
        for name, source in (("ssh", FAKE_SSH), ("scp", FAKE_SSH), ("docker", FAKE_DOCKER)):
            path = self.bin / name
            path.write_text(f"#!{sys.executable}\n{source}")
            path.chmod(0o755)
        self.images.write_text("")
        self.configure("[settings]\ndefault = uat\nuser = daywarden\n[uat]\nhost = uat-box\n[prod]\nhost = prod-box\nuser = admin\nport = 2222\n")

    def configure(self, text: str) -> None:
        self.config.write_text(text)

    def package(self, version: str, *, install: str = INSTALL) -> Path:
        source = self.dist.parent / "source" / f"daywarden-{version}"
        source.mkdir(parents=True, exist_ok=True)
        (source / "VERSION").write_text(version + "\n")
        (source / "install.sh").write_text(install)
        (source / "install.sh").chmod(0o755)
        tarball = self.dist / f"daywarden-{version}.tar.gz"
        with tarfile.open(tarball, "w:gz") as archive:
            archive.add(source, arcname=source.name)
        return tarball

    def old_versions(self, *versions: str) -> None:
        for version in versions:
            (self.remote / f"daywarden-{version}").mkdir()
            held = self.images.read_text().split()
            held += [f"daywarden-policy:{version}", f"daywarden-proxy:{version}"]
            self.images.write_text("\n".join(held))

    def directories(self) -> list[str]:
        return sorted(path.name.removeprefix("daywarden-") for path in self.remote.glob("daywarden-*") if path.is_dir())

    def calls(self) -> list[list[str]]:
        if not self.calls_log.exists():
            return []
        return [json.loads(line) for line in self.calls_log.read_text().splitlines()]

    def copies(self) -> int:
        return sum(call[0] == "scp" for call in self.calls())

    def run(self, *args: str, answer: str = "y", **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "deploy.push", "--config", str(self.config), "--dist", str(self.dist), *args],
            cwd=ROOT,
            input=answer + "\n",
            capture_output=True,
            text=True,
            timeout=60,
            env={
                **os.environ,
                "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "FAKE_REMOTE": str(self.remote),
                "FAKE_CALLS": str(self.calls_log),
                "FAKE_IMAGES": str(self.images),
                **env,
            },
        )


@pytest.fixture
def host(tmp_path):
    return Deployment(tmp_path)


def test_the_newest_package_is_installed_on_the_default_environment(host):
    host.package(OLD[0])
    host.package(NEW)

    result = host.run()

    assert result.returncode == 0, result.stderr
    assert f"Deploying {NEW}" in result.stdout
    assert "to uat (daywarden@uat-box)" in result.stdout
    assert (host.remote / "daywarden" / "VERSION").read_text().strip() == NEW
    assert (host.remote / "answers").read_text() == "y\n"
    assert host.directories() == [NEW]
    assert not list(host.remote.glob("*.tar.gz"))
    # dw status exits 1 here, as on a first install, and the deploy still succeeds.
    assert f"status of {NEW}" in result.stdout


def test_every_step_shares_one_connection_which_is_closed_at_the_end(host):
    host.package(NEW)

    assert host.run("--env", "prod").returncode == 0

    calls = host.calls()
    paths = {arg for call in calls for arg in call if arg.startswith("ControlPath=")}
    assert len(paths) == 1
    assert all(paths <= set(call) and "Port=2222" in call for call in calls)
    assert "-M" in calls[0]
    assert "exit" in calls[-1]
    assert sum("-M" in call for call in calls) == 1
    assert calls[0][-1] == "admin@prod-box"
    install = [call for call in calls if "install.sh" in call[-1]]
    assert len(install) == 1 and "-t" in install[0]


def test_a_named_version_is_installed_instead_of_the_newest(host):
    host.package(OLD[0])
    host.package(NEW)

    result = host.run("--version", OLD[0])

    assert result.returncode == 0, result.stderr
    assert (host.remote / "daywarden" / "VERSION").read_text().strip() == OLD[0]


@pytest.mark.parametrize("dist", ["missing", "empty", "without the version"])
def test_a_package_that_is_not_in_dist_fails_before_connecting(host, dist):
    args = []
    if dist == "missing":
        host.dist.rmdir()
    elif dist == "without the version":
        host.package(NEW)
        host.old_versions(OLD[0])
        args = ["--version", OLD[0]]

    result = host.run(*args)

    assert result.returncode == 1
    assert "no package" in result.stderr
    assert host.calls() == []


@pytest.mark.parametrize(
    "config, args, message",
    [
        ("[uat]\nhost = a\n[prod]\nhost = b\n", [], "sets no default. The environments"),
        ("[uat]\nhost = a\n[prod]\nhost = b\n", ["--env", "qa"], "are: uat, prod."),
        ("[settings]\ndefault = qa\n[uat]\nhost = a\n", [], "no environment named qa"),
        ("[uat]\nhost = a\n", ["--env", "settings"], "no environment named settings"),
        ("[uat]\nuser = a\n", ["--env", "uat"], "[uat] has no host"),
        ("[uat]\nhost = a\npasword = b\n", ["--env", "uat"], "unknown setting, pasword"),
        ("[settings]\nport = 22\n[uat]\nhost = a\n", ["--env", "uat"], "unknown setting, port"),
        ("[uat]\nhost = a\nport = 70000\n", ["--env", "uat"], "port must be a whole number from 1 to 65535"),
        ("[uat]\nhost = a\nkeep = 0\n", ["--env", "uat"], "keep must be a whole number of at least 1"),
        ("[uat]\nhost = -oProxyCommand=x\n", ["--env", "uat"], "is not a host name"),
        ("host = a\n", [], "cannot be read"),
    ],
)
def test_a_wrong_environments_file_or_name_fails_before_connecting(host, config, args, message):
    host.package(NEW)
    host.configure(config)

    result = host.run(*args)

    assert result.returncode == 1
    assert message in result.stderr
    assert host.calls() == []


def test_a_missing_environments_file_says_to_copy_the_sample(host):
    host.config.unlink()

    result = host.run()

    assert result.returncode == 1
    assert "Copy environments.ini.sample to environments.ini" in result.stderr


def test_the_committed_sample_is_a_usable_environments_file():
    from deploy.push import load_environment

    sample = ROOT / "deploy" / "environments.ini.sample"

    assert load_environment(sample, "").name == "uat"
    assert load_environment(sample, "prod").keep == 3


def test_without_a_user_ssh_chooses_one(host):
    host.package(NEW)
    host.configure("[uat]\nhost = uat-box\n")

    assert host.run("--env", "uat").returncode == 0
    assert host.calls()[0][-1] == "uat-box"


def test_a_version_already_there_is_installed_again_without_copying(host):
    host.package(NEW)
    assert host.run().returncode == 0

    result = host.run()

    assert result.returncode == 0, result.stderr
    assert "already there" in result.stdout
    assert host.copies() == 1
    assert (host.remote / "answers").read_text() == "y\ny\n"


def test_a_directory_no_deploy_finished_unpacking_is_replaced(host):
    host.package(NEW)
    partial = host.remote / f"daywarden-{NEW}"
    partial.mkdir()
    (partial / "install.sh").write_text("exit 9\n")

    result = host.run()

    assert result.returncode == 0, result.stderr
    assert "Replacing it" in result.stdout
    assert host.copies() == 1


def test_a_damaged_package_leaves_no_directory_to_reuse(host):
    tarball = host.package(NEW)
    whole = tarball.read_bytes()
    tarball.write_bytes(whole[: len(whole) // 2])

    result = host.run()

    assert result.returncode != 0
    assert "Unpacking" in result.stderr
    assert host.directories() == []
    assert not list(host.remote.glob(".daywarden-*"))
    tarball.write_bytes(whole)
    assert host.run().returncode == 0


def test_a_refused_install_fails_keeps_every_version_and_can_be_tried_again(host):
    host.old_versions(*OLD)
    host.package(NEW)

    result = host.run(answer="n")

    assert result.returncode == 1
    assert "install.sh did not finish" in result.stderr
    assert host.directories() == [*OLD, NEW]
    assert "status of" not in result.stdout
    assert "exit" in host.calls()[-1]
    assert host.run().returncode == 0
    assert host.copies() == 1


def test_a_failed_connection_copies_nothing(host):
    host.package(NEW)

    result = host.run(FAKE_CONNECT="255")

    assert result.returncode == 255
    assert "Could not connect to daywarden@uat-box" in result.stderr
    assert len(host.calls()) == 1


def test_old_versions_their_packages_and_images_are_removed(host):
    host.old_versions(*OLD)
    (host.remote / f"daywarden-{OLD[0]}.tar.gz").write_text("left over")
    others = ["daywarden-notes", f"daywarden-{OLD[0]}-saved"]
    for name in others:
        (host.remote / name).mkdir()
    host.package(NEW)

    result = host.run()

    assert result.returncode == 0, result.stderr
    kept = [path.name for path in host.remote.iterdir() if path.name.startswith("daywarden")]
    assert sorted(kept) == sorted(["daywarden", *others, *(f"daywarden-{version}" for version in (*OLD[2:], NEW))])
    assert sorted(host.images.read_text().split()) == sorted(
        f"daywarden-{kind}:{version}" for kind in ("policy", "proxy") for version in OLD[2:]
    )
    assert f"Removed ~/daywarden-{OLD[0]}.tar.gz" in result.stdout
    assert f"Removed image daywarden-proxy:{OLD[1]}" in result.stdout


def test_an_older_version_that_is_installed_is_kept_beside_the_newest(host):
    host.old_versions(*OLD[1:])
    host.package(OLD[0])
    host.configure("[uat]\nhost = uat-box\nkeep = 1\n")

    result = host.run("--env", "uat")

    assert result.returncode == 0, result.stderr
    assert host.directories() == [OLD[0], OLD[3]]


def test_an_image_that_cannot_be_removed_is_only_a_warning(host):
    host.old_versions(*OLD)
    host.package(NEW)

    result = host.run(FAKE_IN_USE=f"daywarden-policy:{OLD[0]}")

    assert result.returncode == 0
    assert f"Warning: could not remove image daywarden-policy:{OLD[0]}" in result.stdout
    assert f"daywarden-proxy:{OLD[0]}" not in host.images.read_text()


@pytest.mark.parametrize(
    "make_args, environment, expected",
    [
        ([], {"ENV": "/etc/profile", "VERSION": "9"}, '--env "" --version ""'),
        (["ENV=prod", f"VERSION={NEW}"], {}, f'--env "prod" --version "{NEW}"'),
    ],
)
def test_make_deploy_takes_env_and_version_only_from_its_command_line(make_args, environment, expected):
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", "-o", ".venv/.installed", "deploy", *make_args],
        cwd=ROOT,
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        check=True,
    )

    assert expected in result.stdout
