"""S014: make dist turns the development compose file and .env into the package's copies."""

import pytest
import yaml

from hostfakes import ROOT
from deploy.build import installed_compose, sample_env

DEV_COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(installed_compose(DEV_COMPOSE, "20261105-184500"))


def test_the_installed_stack_runs_the_packaged_images_and_never_builds_or_pulls(compose):
    services = compose["services"]
    assert set(services) == {"decisions", "observations", "proxy", "autoconfig"}
    for name in ("decisions", "observations", "autoconfig"):
        assert services[name]["image"] == "daywarden-policy:20261105-184500"
    assert services["proxy"]["image"] == "daywarden-proxy:20261105-184500"
    for service in services.values():
        assert "build" not in service
        assert service["pull_policy"] == "never"
        assert service["restart"] == "on-failure"


def test_the_installed_proxy_mounts_no_source_and_keeps_its_ca_and_config(compose):
    volumes = compose["services"]["proxy"]["volumes"]
    assert volumes == ["${CA_VOLUME_PATH}:/home/mitmproxy/.mitmproxy", "${DAYWARDEN_CONFIG_DIR:-./config}:/etc/daywarden:ro"]
    assert compose["services"]["proxy"]["entrypoint"] == ["/bin/bash", "/opt/daywarden/entrypoint.sh"]


def test_the_installed_data_directory_defaults_under_daywarden_data(compose):
    data = [volume for volume in compose["services"]["decisions"]["volumes"] if isinstance(volume, dict)]
    assert [volume["source"] for volume in data] == ["${DAYWARDEN_DATA_DIR:-${HOME}/daywarden/data}"]
    assert data[0]["read_only"] is False


def test_the_development_compose_file_is_left_for_make_up():
    development = yaml.safe_load(DEV_COMPOSE)
    assert development["services"]["decisions"]["build"] == "./policy"
    assert development["services"]["proxy"]["restart"] == "unless-stopped"


def test_a_compose_file_without_the_data_mount_is_refused():
    broken = DEV_COMPOSE.replace("${DAYWARDEN_DATA_DIR:-${HOME}/daywarden}", "/srv/data")
    with pytest.raises(ValueError, match="does not mount"):
        installed_compose(broken, "v")


def test_the_sample_env_puts_the_ca_and_data_under_daywarden_and_keeps_the_rest():
    text = "PROXY_PORT=8080\n# CA here\nCA_VOLUME_PATH=./data/ca\nPARENT_NAMES=garden,localhost\nDAYWARDEN_DATA_DIR=${HOME}/daywarden\n"
    assert sample_env(text) == (
        "PROXY_PORT=8080\n# CA here\nCA_VOLUME_PATH=${HOME}/daywarden/ca\nPARENT_NAMES=garden,localhost\n"
        "DAYWARDEN_DATA_DIR=${HOME}/daywarden/data\n"
    )
    with pytest.raises(ValueError, match="CA_VOLUME_PATH"):
        sample_env("PROXY_PORT=8080\n")
