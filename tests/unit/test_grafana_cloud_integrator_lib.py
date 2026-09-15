import pytest
from charms.grafana_cloud_integrator.v0.cloud_config_requirer import (
    CREDENTIALS_SECRET_LABEL,
    CloudConfigAvailableEvent,
    CloudConfigRevokedEvent,
    GrafanaCloudConfigRequirer,
)
from ops import CharmBase, Framework
from scenario import Context, Relation, Secret, State


class MyCharm(CharmBase):
    def __init__(self, framework: Framework):
        super().__init__(framework)
        self.cloud = GrafanaCloudConfigRequirer(self)


@pytest.fixture()
def mycharm_context():
    """Returns a Context object with a MyCharm instance."""
    return Context(
        charm_type=MyCharm,
        meta={
            "name": "my-charm",
            "requires": {
                "grafana-cloud-config": {"interface": "grafana_cloud_config", "limit": 1}
            },
        },
    )


@pytest.mark.parametrize("is_leader", [(True,), (False,)])
def test_requirer_emits_cloud_config_available_event_on_relation_changed(
    is_leader, mycharm_context
):
    # GIVEN a grafana-cloud-config relation and a leadership status
    grafana_cloud_config_relation = Relation("grafana-cloud-config")
    state = State(leader=is_leader, relations=[grafana_cloud_config_relation])

    # WHEN the grafana-cloud-config relation changes
    mycharm_context.run(
        mycharm_context.on.relation_changed(relation=grafana_cloud_config_relation), state
    )

    # THEN the CloudConfigAvailableEvent event is emitted
    assert any(
        event
        for event in mycharm_context.emitted_events
        if isinstance(event, CloudConfigAvailableEvent)
    )


@pytest.mark.parametrize("is_leader", [(True,), (False,)])
def test_requirer_emits_cloud_config_revoked_event_on_relation_broken(is_leader, mycharm_context):
    # GIVEN a grafana-cloud-config relation
    grafana_cloud_config_relation = Relation("grafana-cloud-config")
    # AND GIVEN leadership/non-leadership
    state = State(leader=is_leader, relations=[grafana_cloud_config_relation])

    # WHEN the grafana-cloud-config relation changes
    mycharm_context.run(
        mycharm_context.on.relation_broken(relation=grafana_cloud_config_relation), state
    )

    # THEN the CloudConfigAvailableEvent event is emitted
    assert any(
        event
        for event in mycharm_context.emitted_events
        if isinstance(event, CloudConfigRevokedEvent)
    )


def test_requirer_reads_the_credentials_from_a_secret(mycharm_context):
    # GIVEN a provider that shared a secret id rather than plain-text credentials
    secret = Secret(
        {"username": "a-username", "password": "a-password"},
        label=CREDENTIALS_SECRET_LABEL,
    )
    relation = Relation(
        "grafana-cloud-config",
        remote_app_data={"secret-id": secret.id, "loki_url": "https://example.org"},
    )
    state = State(relations=[relation], secrets=[secret])

    # WHEN the charm looks at the credentials
    with mycharm_context(mycharm_context.on.relation_changed(relation=relation), state) as manager:
        manager.run()
        credentials = manager.charm.cloud.credentials

    # THEN they come from the secret
    assert credentials.username == "a-username"
    assert credentials.password == "a-password"


def test_requirer_falls_back_to_plain_text_credentials(mycharm_context):
    # GIVEN a provider too old to share a secret
    relation = Relation(
        "grafana-cloud-config",
        remote_app_data={"username": "a-username", "password": "a-password"},
    )
    state = State(relations=[relation])

    # WHEN the charm looks at the credentials
    with mycharm_context(mycharm_context.on.relation_changed(relation=relation), state) as manager:
        manager.run()
        credentials = manager.charm.cloud.credentials

    # THEN it still gets them
    assert credentials.username == "a-username"


def test_requirer_has_no_credentials_when_the_secret_is_not_readable(mycharm_context):
    # GIVEN a secret id we have not been granted
    relation = Relation(
        "grafana-cloud-config",
        remote_app_data={"secret-id": "secret:cvh7kruupa1s46bqvuig"},
    )
    state = State(relations=[relation])

    # WHEN the charm looks at the credentials
    with mycharm_context(mycharm_context.on.relation_changed(relation=relation), state) as manager:
        manager.run()
        credentials = manager.charm.cloud.credentials

    # THEN there are none, rather than an exception
    assert credentials is None


def test_requirer_emits_cloud_config_available_on_secret_changed(mycharm_context):
    # GIVEN a credentials secret with a new revision
    secret = Secret(
        tracked_content={"username": "a-username", "password": "old-password"},
        latest_content={"username": "a-username", "password": "new-password"},
        label=CREDENTIALS_SECRET_LABEL,
    )
    relation = Relation("grafana-cloud-config", remote_app_data={"secret-id": secret.id})
    state = State(relations=[relation], secrets=[secret])

    # WHEN the secret changes
    with mycharm_context(mycharm_context.on.secret_changed(secret), state) as manager:
        manager.run()
        credentials = manager.charm.cloud.credentials

    # THEN the charm is told to reconfigure, with the new revision
    assert any(
        event
        for event in mycharm_context.emitted_events
        if isinstance(event, CloudConfigAvailableEvent)
    )
    assert credentials.password == "new-password"
