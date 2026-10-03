#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Requirer charm for the grafana-cloud-config integration tests."""

import hashlib

import ops
from charms.grafana_cloud_integrator.v0.cloud_config_requirer import GrafanaCloudConfigRequirer


class TesterCharm(ops.CharmBase):
    """Reports the credentials it receives in its status."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.cloud = GrafanaCloudConfigRequirer(self)
        framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)

    def _on_collect_unit_status(self, event: ops.CollectStatusEvent):
        credentials = self.cloud.credentials
        if credentials is None:
            event.add_status(ops.ActiveStatus("no credentials"))
            return
        # A fingerprint shows which password arrived without putting it in the status.
        fingerprint = hashlib.sha256(credentials.password.encode()).hexdigest()[:8]
        event.add_status(ops.ActiveStatus(f"{credentials.username} {fingerprint}"))


if __name__ == "__main__":  # pragma: nocover
    ops.main(TesterCharm)
