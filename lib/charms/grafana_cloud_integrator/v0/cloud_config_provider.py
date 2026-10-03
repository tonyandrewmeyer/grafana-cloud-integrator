"""Grafana Cloud Integrator Configuration Provider.

The endpoint URLs and the TLS CA are shared in the application databag. The
credentials are shared as a Juju secret: the databag holds only its
`secret-id`, and the secret is granted to each related application.

Before LIBPATCH 6, this library wrote `username` and `password` into the
databag in plain text. It now removes those keys from every existing relation,
on `upgrade-charm` as well as on the relation and config events, so upgrading
the charm doesn't leave the plain-text credentials behind.
"""

from typing import Optional

import ops
from ops.framework import Object

LIBID = "2a48eccc49a346f08879b11ecab4465a"
LIBAPI = 0
LIBPATCH = 6

DEFAULT_RELATION_NAME = "grafana-cloud-config"

SECRET_LABEL = "grafana-cloud-config-credentials"
_PLAIN_TEXT_KEYS = ("username", "password")


class Credentials:
    """Credentials for the remote endpoints."""

    def __init__(self, username, password):
        self.username = username
        self.password = password


class GrafanaCloudConfigProvider(Object):
    """Provider side of the Grafana Cloud Config relation."""

    def __init__(
        self,
        charm,
        credentials: Credentials,
        prometheus_url: str,
        loki_url: str,
        tempo_url: str,
        relation_name: str = DEFAULT_RELATION_NAME,
    ):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._credentials = credentials
        self._prometheus_url = prometheus_url
        self._loki_url = loki_url
        self._tempo_url = tempo_url
        self._relation_name = relation_name

        relation_events = self._charm.on[relation_name]

        for event in [
            relation_events.relation_joined,
            relation_events.relation_created,
            relation_events.relation_changed,
            self._charm.on.config_changed,
            # Relations that an earlier revision set up aren't joined again
            # after an upgrade, so move them over to the secret now.
            self._charm.on.upgrade_charm,
        ]:
            self.framework.observe(
                event,
                self._on_relation_changed,
            )
        self.framework.observe(self._charm.on.secret_remove, self._on_secret_remove)

    def _on_relation_changed(self, event):
        if not self._charm.unit.is_leader():
            return

        secret_id = self._update_secret()

        for relation in self._charm.model.relations[self._relation_name]:
            databag = relation.data[self._charm.app]

            for key in _PLAIN_TEXT_KEYS:
                databag.pop(key, None)
            if secret_id is None:
                databag.pop("secret-id", None)
            else:
                databag["secret-id"] = secret_id
            if self._loki_url:
                databag["loki_url"] = self._loki_url
            if self._tempo_url:
                databag["tempo_url"] = self._tempo_url
            if self._prometheus_url:
                databag["prometheus_url"] = self._prometheus_url
            databag["tls-ca"] = self._charm.config.get("tls-ca", "")

    def _update_secret(self) -> Optional[str]:
        """Create, update or remove the credentials secret to match the config.

        Returns:
            The secret's ID, or None if the credentials aren't configured.
        """
        try:
            secret = self._charm.model.get_secret(label=SECRET_LABEL)
        except ops.SecretNotFoundError:
            secret = None

        username = self._credentials.username
        password = self._credentials.password
        if not (username and password):
            # Clearing the credentials has to remove the secret, or the
            # requirer keeps using credentials the administrator withdrew.
            if secret is not None:
                secret.remove_all_revisions()
            return None

        content = {"username": username, "password": password}
        if secret is None:
            secret = self._charm.app.add_secret(content, label=SECRET_LABEL)
        elif secret.get_content(refresh=True) != content:
            secret.set_content(content)
        for relation in self._charm.model.relations[self._relation_name]:
            secret.grant(relation)
        return secret.get_info().id

    def _on_secret_remove(self, event: ops.SecretRemoveEvent):
        # Changing the credentials creates a new revision. Once no requirer
        # is tracking the old one, remove it.
        if event.secret.label == SECRET_LABEL:
            event.remove_revision()
