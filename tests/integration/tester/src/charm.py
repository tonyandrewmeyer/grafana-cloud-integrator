#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Requirer charm for the grafana-cloud-config integration tests."""

import ops
from charms.grafana_cloud_integrator.v0.cloud_config_requirer import GrafanaCloudConfigRequirer


class TesterCharm(ops.CharmBase):
    """Reports the credentials it receives."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.cloud = GrafanaCloudConfigRequirer(self)
        framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)
        framework.observe(self.on["get-credentials"].action, self._on_get_credentials)

    def _on_collect_unit_status(self, event: ops.CollectStatusEvent):
        credentials = self.cloud.credentials
        event.add_status(
            ops.ActiveStatus(credentials.username if credentials else "no credentials")
        )

    def _on_get_credentials(self, event: ops.ActionEvent):
        credentials = self.cloud.credentials
        if credentials is None:
            event.set_results({"username": "", "password": ""})
        else:
            event.set_results({"username": credentials.username, "password": credentials.password})


if __name__ == "__main__":  # pragma: nocover
    ops.main(TesterCharm)
