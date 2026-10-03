#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
TESTER = "tester"
TESTER_DIR = Path("tests/integration/tester")
REQUIRER_LIB = Path("lib/charms/grafana_cloud_integrator/v0/cloud_config_requirer.py")


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # Build and deploy charm from local source folder
    assert ops_test.model

    if os.environ.get("CHARM_PATH"):
        charm = os.environ.get("CHARM_PATH")
    else:
        charm = await ops_test.build_charm(".")

    # Deploy the charm and wait for active/idle status
    await ops_test.model.deploy(charm, application_name=APP_NAME)
    app = ops_test.model.applications.get(APP_NAME)
    assert app
    await app.set_config(
        {
            "username": "a-username",
            "password": "a-password",
            "loki-url": "http://a-loki-url",
            "tempo-url": "http://a-tempo-url",
            "prometheus-url": "http://a-prom-url",
        }
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=False,
        timeout=1000,
    )


async def wait_for_tester_credentials(ops_test: OpsTest, username: str, password: str):
    """Wait until the tester reports these credentials, or none if they're empty."""
    assert ops_test.model
    unit = ops_test.model.applications[TESTER].units[0]
    expected = {"username": username, "password": password}
    results = {}
    for _ in range(60):
        action = await (await unit.run_action("get-credentials")).wait()
        results = {key: action.results.get(key, "") for key in expected}
        if results == expected:
            return
        await asyncio.sleep(10)
    raise AssertionError(f"tester reports {results.get('username')!r}, expected {username!r}")


async def integrator_app_data(ops_test: OpsTest) -> dict:
    """The integrator's application data, as the tester sees it."""
    _, stdout, _ = await ops_test.juju("show-unit", f"{TESTER}/0", "--format=json")
    relation_info = json.loads(stdout)[f"{TESTER}/0"]["relation-info"]
    (relation,) = [r for r in relation_info if r["endpoint"] == "grafana-cloud-config"]
    return relation["application-data"]


@pytest.mark.abort_on_fail
async def test_requirer_gets_the_credentials_from_a_secret(ops_test: OpsTest):
    assert ops_test.model
    lib_dir = TESTER_DIR / REQUIRER_LIB.parent
    lib_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(REQUIRER_LIB, lib_dir)
    tester = await ops_test.build_charm(TESTER_DIR)

    await ops_test.model.deploy(tester, application_name=TESTER)
    await ops_test.model.integrate(f"{APP_NAME}:grafana-cloud-config", TESTER)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, TESTER], status="active", timeout=1000)

    await wait_for_tester_credentials(ops_test, "a-username", "a-password")
    data = await integrator_app_data(ops_test)
    assert "secret-id" in data
    assert "username" not in data
    assert "password" not in data


async def test_a_new_password_reaches_the_requirer(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.applications[APP_NAME].set_config({"password": "b-password"})
    await wait_for_tester_credentials(ops_test, "a-username", "b-password")


async def test_clearing_the_password_withdraws_the_credentials(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.applications[APP_NAME].set_config({"password": ""})
    await wait_for_tester_credentials(ops_test, "", "")
    assert "secret-id" not in await integrator_app_data(ops_test)


async def test_setting_the_password_again_shares_a_new_secret(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.applications[APP_NAME].set_config({"password": "c-password"})
    await wait_for_tester_credentials(ops_test, "a-username", "c-password")
