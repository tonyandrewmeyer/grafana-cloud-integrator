# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import pytest
from charms.grafana_cloud_integrator.v0.cloud_config_provider import SECRET_LABEL
from charms.grafana_cloud_integrator.v0.cloud_config_requirer import (
    CloudConfigAvailableEvent,
    GrafanaCloudConfigRequirer,
)
from ops import CharmBase, Framework, testing

from charm import GrafanaCloudIntegratorCharm

RELATION = "grafana-cloud-config"
CONFIG: dict[str, str | int | float | bool] = {
    "username": "a-username",
    "password": "a-password",
    "loki-url": "https://loki.example.com",
}


@pytest.fixture
def ctx():
    return testing.Context(GrafanaCloudIntegratorCharm)


def credentials_secret(state: testing.State) -> testing.Secret:
    (secret,) = [s for s in state.secrets if s.label == SECRET_LABEL]
    return secret


def test_upgrade_moves_plain_text_credentials_to_a_secret(ctx: testing.Context):
    # An earlier revision of the charm wrote the credentials in plain text.
    relation = testing.Relation(
        RELATION,
        local_app_data={"username": "a-username", "password": "a-password"},
    )
    state = testing.State(leader=True, config=CONFIG, relations={relation})

    out = ctx.run(ctx.on.upgrade_charm(), state)

    databag = out.get_relation(relation.id).local_app_data
    assert "username" not in databag
    assert "password" not in databag
    secret = credentials_secret(out)
    assert databag["secret-id"] == secret.id
    assert secret.tracked_content == {"username": "a-username", "password": "a-password"}
    assert relation.id in secret.remote_grants


def test_new_relation_after_upgrade_gets_the_same_secret(ctx: testing.Context):
    old = testing.Relation(RELATION, local_app_data={"username": "u", "password": "p"})
    state = testing.State(leader=True, config=CONFIG, relations={old})
    state = ctx.run(ctx.on.upgrade_charm(), state)
    new = testing.Relation(RELATION)
    state = testing.State(
        leader=True, config=CONFIG, relations={*state.relations, new}, secrets=state.secrets
    )

    out = ctx.run(ctx.on.relation_joined(new, remote_unit=0), state)

    secret = credentials_secret(out)
    assert out.get_relation(new.id).local_app_data["secret-id"] == secret.id
    assert out.get_relation(old.id).local_app_data["secret-id"] == secret.id
    assert {old.id, new.id} <= set(secret.remote_grants)


def test_second_upgrade_does_not_create_another_secret(ctx: testing.Context):
    relation = testing.Relation(RELATION, local_app_data={"username": "u", "password": "p"})
    state = testing.State(leader=True, config=CONFIG, relations={relation})

    state = ctx.run(ctx.on.upgrade_charm(), state)
    out = ctx.run(ctx.on.upgrade_charm(), state)

    assert len(list(out.secrets)) == 1
    assert credentials_secret(out).latest_content == credentials_secret(state).latest_content


def test_non_leader_leaves_the_databag_alone(ctx: testing.Context):
    databag = {"username": "a-username", "password": "a-password"}
    relation = testing.Relation(RELATION, local_app_data=databag)
    state = testing.State(leader=False, config=CONFIG, relations={relation})

    out = ctx.run(ctx.on.upgrade_charm(), state)

    assert out.get_relation(relation.id).local_app_data == databag
    assert not out.secrets


def test_changing_the_password_updates_the_secret(ctx: testing.Context):
    relation = testing.Relation(RELATION)
    state = ctx.run(
        ctx.on.config_changed(),
        testing.State(leader=True, config=CONFIG, relations={relation}),
    )
    state = testing.State(
        leader=True,
        config={**CONFIG, "password": "a-new-password"},
        relations=state.relations,
        secrets=state.secrets,
    )

    out = ctx.run(ctx.on.config_changed(), state)

    assert len(list(out.secrets)) == 1
    assert credentials_secret(out).latest_content == {
        "username": "a-username",
        "password": "a-new-password",
    }


def test_clearing_the_credentials_removes_the_secret(ctx: testing.Context):
    relation = testing.Relation(RELATION)
    state = ctx.run(
        ctx.on.config_changed(),
        testing.State(leader=True, config=CONFIG, relations={relation}),
    )
    secret_id = credentials_secret(state).id
    state = testing.State(
        leader=True,
        config={**CONFIG, "password": ""},
        relations=state.relations,
        secrets=state.secrets,
    )

    out = ctx.run(ctx.on.config_changed(), state)

    assert "secret-id" not in out.get_relation(relation.id).local_app_data
    assert all(s.id != secret_id for s in out.secrets)


def test_secret_remove_removes_the_old_revision(ctx: testing.Context):
    # Create the secret, then change the password twice, so that revision 1
    # is neither the latest nor the tracked revision.
    state = testing.State(leader=True, config=CONFIG)
    for password in ("a-password", "a-second-password", "a-third-password"):
        state = ctx.run(
            ctx.on.config_changed(),
            testing.State(
                leader=True, config={**CONFIG, "password": password}, secrets=state.secrets
            ),
        )

    ctx.run(ctx.on.secret_remove(credentials_secret(state), revision=1), state)

    assert ctx.removed_secret_revisions == [1]


class RequirerCharm(CharmBase):
    def __init__(self, framework: Framework):
        super().__init__(framework)
        self.cloud = GrafanaCloudConfigRequirer(self)


REQUIRER_META = {
    "name": "requirer",
    "requires": {RELATION: {"interface": "grafana_cloud_config", "limit": 1}},
}


@pytest.fixture
def requirer_ctx():
    return testing.Context(RequirerCharm, meta=REQUIRER_META)


def test_requirer_reads_credentials_from_the_secret(requirer_ctx: testing.Context):
    secret = testing.Secret({"username": "a-username", "password": "a-password"})
    relation = testing.Relation(RELATION, remote_app_data={"secret-id": secret.id})
    state = testing.State(relations={relation}, secrets={secret})

    with requirer_ctx(requirer_ctx.on.relation_changed(relation), state) as mgr:
        mgr.run()
        credentials = mgr.charm.cloud.credentials

    assert credentials is not None
    assert (credentials.username, credentials.password) == ("a-username", "a-password")


def test_requirer_falls_back_to_plain_text_credentials(requirer_ctx: testing.Context):
    relation = testing.Relation(
        RELATION, remote_app_data={"username": "a-username", "password": "a-password"}
    )
    state = testing.State(relations={relation})

    with requirer_ctx(requirer_ctx.on.relation_changed(relation), state) as mgr:
        mgr.run()
        credentials = mgr.charm.cloud.credentials

    assert credentials is not None
    assert (credentials.username, credentials.password) == ("a-username", "a-password")


def test_requirer_has_no_credentials_when_the_secret_is_gone(requirer_ctx: testing.Context):
    relation = testing.Relation(
        RELATION, remote_app_data={"secret-id": "secret:0123456789abcdefghij"}
    )
    state = testing.State(relations={relation})

    with requirer_ctx(requirer_ctx.on.relation_changed(relation), state) as mgr:
        mgr.run()
        assert mgr.charm.cloud.credentials is None


def test_requirer_emits_available_when_the_secret_changes(requirer_ctx: testing.Context):
    secret = testing.Secret(
        {"username": "a-username", "password": "a-password"}, label=SECRET_LABEL
    )
    relation = testing.Relation(RELATION, remote_app_data={"secret-id": secret.id})
    state = testing.State(relations={relation}, secrets={secret})

    requirer_ctx.run(requirer_ctx.on.secret_changed(secret), state)

    assert any(isinstance(e, CloudConfigAvailableEvent) for e in requirer_ctx.emitted_events)
