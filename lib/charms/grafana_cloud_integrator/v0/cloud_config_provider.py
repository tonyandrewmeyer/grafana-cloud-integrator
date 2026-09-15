"""Grafana Cloud Integrator Configuration Requirer."""

import logging

import ops
from ops.framework import Object

LIBID = "2a48eccc49a346f08879b11ecab4465a"
LIBAPI = 0
LIBPATCH = 6

DEFAULT_RELATION_NAME = "grafana-cloud-config"

# Charm-local label for the secret this charm owns and grants to the requirers.
CREDENTIALS_SECRET_LABEL = "grafana-cloud-config-credentials"

# Relation data keys that held the credentials in plain text before LIBPATCH 6.
LEGACY_CREDENTIALS_KEYS = ("username", "password")

logger = logging.getLogger(__name__)


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
        ]:
            self.framework.observe(
                event,
                self._on_relation_changed,
            )

        self.framework.observe(self._charm.on.secret_remove, self._on_secret_remove)

    def set_credentials(self, credentials: Credentials):
        """Replace the credentials shared over the relation, and publish them."""
        self._credentials = credentials
        self._publish()

    def _on_relation_changed(self, event):
        self._publish()

    def _on_secret_remove(self, event: ops.SecretRemoveEvent):
        # No requirer is tracking this revision any more, so it can go.
        if event.secret.label == CREDENTIALS_SECRET_LABEL:
            event.remove_revision()

    def _publish(self):
        if not self._charm.unit.is_leader():
            return

        secret = self._sync_secret()

        for relation in self._charm.model.relations[self._relation_name]:
            databag = relation.data[self._charm.app]

            if secret is not None and secret.id:
                secret.grant(relation)
                databag["secret-id"] = secret.id
            elif "secret-id" in databag:
                del databag["secret-id"]
            # Before LIBPATCH 6 the credentials were written here in plain text. An
            # upgraded charm has to clear them out, or they stay in the databag for
            # the life of the relation.
            for key in LEGACY_CREDENTIALS_KEYS:
                if key in databag:
                    del databag[key]

            if self._loki_url:
                databag["loki_url"] = self._loki_url
            if self._tempo_url:
                databag["tempo_url"] = self._tempo_url
            if self._prometheus_url:
                databag["prometheus_url"] = self._prometheus_url
            databag["tls-ca"] = self._charm.config.get("tls-ca", "")

    def _sync_secret(self):
        """Create or update the secret holding the credentials, if there are any."""
        content = {
            "username": self._credentials.username if self._credentials else "",
            "password": self._credentials.password if self._credentials else "",
        }
        if not all(value.strip() for value in content.values()):
            # Juju secrets cannot hold empty values, and there is nothing to share yet.
            # If we shared some before, the credentials have been withdrawn: don't
            # leave them lying around in the secret backend.
            try:
                self._charm.model.get_secret(label=CREDENTIALS_SECRET_LABEL).remove_all_revisions()
            except ops.SecretNotFoundError:
                pass
            return None

        try:
            secret = self._charm.model.get_secret(label=CREDENTIALS_SECRET_LABEL)
        except ops.SecretNotFoundError:
            return self._charm.app.add_secret(
                content,
                label=CREDENTIALS_SECRET_LABEL,
                description="Grafana Cloud credentials, shared over grafana-cloud-config.",
            )

        if secret.get_content() != content:
            secret.set_content(content)
        return secret
