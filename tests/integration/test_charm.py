#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    
    # Deploy the charm and wait for active/idle status
    await ops_test.model.deploy(await charm, application_name=APP_NAME)
    await ops_test.model.set_config({
        "username": "a-username",
        "password": "a-password",
        "loki-url": "http://a-loki-url",
        "prometheus-url": "http://a-prom-url"
    })
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], 
        status="active", 
        raise_on_blocked=True, 
        timeout=1000,
    )
