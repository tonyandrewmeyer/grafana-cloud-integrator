#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Grafana Cloud Integrator Charm."""

import logging
import typing

from charms.grafana_cloud_integrator.v0.cloud_config_provider import (
    Credentials,
    GrafanaCloudConfigProvider,
)
from ops import (
    ActiveStatus,
    BlockedStatus,
    CharmBase,
    CollectStatusEvent,
    ModelError,
    SecretChangedEvent,
    SecretNotFoundError,
)

logger = logging.getLogger(__name__)

# Charm-local label for the user secret named by the "credentials" config option.
USER_SECRET_LABEL = "grafana-cloud-credentials"


class GrafanaCloudIntegratorCharm(CharmBase):
    """Integrates local Grafana Agent deployments with Grafana Cloud."""

    def __init__(self, *args):
        super().__init__(*args)

        # Set by _load_credentials when the "credentials" secret cannot be read.
        self._credentials_error = ""
        self._credentials = self._load_credentials()

        self._config = GrafanaCloudConfigProvider(
            self,
            self._credentials,
            loki_url=typing.cast(str, self.config.get("loki-url", "")),
            tempo_url=typing.cast(str, self.config.get("tempo-url", "")),
            prometheus_url=typing.cast(str, self.config.get("prometheus-url", "")),
        )

        self.framework.observe(self.on.secret_changed, self._on_secret_changed)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)

    def _load_credentials(self, refresh: bool = False) -> Credentials:
        """Read the credentials from the user secret, or from the legacy config options."""
        secret_uri = typing.cast(str, self.config.get("credentials", "")).strip()
        if not secret_uri:
            username = typing.cast(str, self.config.get("username", ""))
            password = typing.cast(str, self.config.get("password", ""))
            if username.strip() or password.strip():
                logger.warning(
                    "The 'username' and 'password' config options are deprecated: "
                    "put the credentials in a user secret and set the 'credentials' "
                    "option to its URI instead."
                )
            return Credentials(username, password)

        try:
            secret = self.model.get_secret(id=secret_uri, label=USER_SECRET_LABEL)
            content = secret.get_content(refresh=refresh)
        except SecretNotFoundError:
            self._credentials_error = "The secret in 'credentials' does not exist."
            return Credentials("", "")
        except ModelError:
            # "juju grant-secret" does not notify the charm, so the administrator
            # may have set the config option before granting access to the secret.
            self._credentials_error = (
                "Cannot read the secret in 'credentials': "
                "has it been granted to this application?"
            )
            return Credentials("", "")

        missing = [key for key in ("username", "password") if not content.get(key, "").strip()]
        if missing:
            self._credentials_error = (
                f"The secret in 'credentials' is missing: {', '.join(missing)}."
            )
        return Credentials(content.get("username", ""), content.get("password", ""))

    def _on_secret_changed(self, event: SecretChangedEvent):
        if event.secret.label != USER_SECRET_LABEL:
            return
        self._credentials = self._load_credentials(refresh=True)
        self._config.set_credentials(self._credentials)

    def _on_collect_unit_status(self, event: CollectStatusEvent):
        # each *-url config option tells us where to send telemetry of a given type.
        # this maps config option names to human-readable telemetry types, so we can report
        # via the status which ones are unset. We strip the config value just in case.
        config_to_signal = (("loki-url", "Logs"), ("tempo-url", "Traces"), ("prometheus-url", "Metrics"))
        output_configs = {
            telemetry: bool(typing.cast(str, self.config.get(key, "")).strip()) for
            key, telemetry in config_to_signal
        }

        if self._credentials_error:
            event.add_status(BlockedStatus(self._credentials_error))
        elif not (self._credentials.username.strip() and self._credentials.password.strip()):
            # FIXME: should this be blocked in fact?
            event.add_status(ActiveStatus("username/password not configured."))

        if not any(output_configs.values()):
            event.add_status(BlockedStatus("No outputs configured"))
        elif any_unset := (k for k, v in output_configs.items() if not v):
            event.add_status(ActiveStatus(f"{', '.join(any_unset)} disabled"))
        else:
            event.add_status(ActiveStatus(""))


if __name__ == "__main__":  # pragma: nocover
    from ops import main

    main(GrafanaCloudIntegratorCharm)
