# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from charms.grafana_cloud_integrator.v0.cloud_config_provider import (
    CREDENTIALS_SECRET_LABEL,
)
from ops import testing

from charm import USER_SECRET_LABEL, GrafanaCloudIntegratorCharm

URLS = {"prometheus-url": "https://example.org", "loki-url": "https://example.org"}


@pytest.fixture()
def ctx():
    return testing.Context(GrafanaCloudIntegratorCharm)


def _find_owned_secret(state):
    """The secret this charm owns, if it created one."""
    for secret in state.secrets:
        if secret.label == CREDENTIALS_SECRET_LABEL:
            return secret
    return None


def _owned_secret(state):
    """The secret this charm owns, failing the test if there isn't one."""
    secret = _find_owned_secret(state)
    assert secret is not None, "the charm did not create a credentials secret"
    return secret


def test_credentials_are_shared_as_a_secret_not_in_plain_text(ctx):
    # GIVEN credentials in config and a requirer related to us
    relation = testing.Relation("grafana-cloud-config")
    state_in = testing.State(
        leader=True,
        relations={relation},
        config=dict(URLS, username="a-username", password="a-password"),
    )

    # WHEN the relation is joined
    state_out = ctx.run(ctx.on.relation_joined(relation), state_in)

    # THEN a secret is created with the credentials, and granted to the requirer
    secret = _owned_secret(state_out)
    assert secret.owner == "app"
    assert secret.tracked_content == {"username": "a-username", "password": "a-password"}
    assert secret.remote_grants == {relation.id: {relation.remote_app_name}}

    # AND the databag has the secret id and no plain-text credentials
    databag = state_out.get_relation(relation.id).local_app_data
    assert databag["secret-id"] == secret.id
    assert "username" not in databag
    assert "password" not in databag


def test_no_secret_is_created_without_credentials(ctx):
    # GIVEN no credentials configured
    relation = testing.Relation("grafana-cloud-config")
    state_in = testing.State(leader=True, relations={relation}, config=dict(URLS))

    # WHEN the relation is joined
    state_out = ctx.run(ctx.on.relation_joined(relation), state_in)

    # THEN there is no secret, and the URLs are still shared
    assert _find_owned_secret(state_out) is None
    databag = state_out.get_relation(relation.id).local_app_data
    assert "secret-id" not in databag
    assert databag["loki_url"] == "https://example.org"


def test_plain_text_credentials_are_removed_on_upgrade(ctx):
    # GIVEN a relation whose databag still holds credentials written by an older charm
    relation = testing.Relation(
        "grafana-cloud-config",
        local_app_data={
            "username": "a-username",
            "password": "a-password",
            "loki_url": "https://example.org",
        },
    )
    state_in = testing.State(
        leader=True,
        relations={relation},
        config=dict(URLS, username="a-username", password="a-password"),
    )

    # WHEN the charm next publishes
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    # THEN the plain-text keys are gone
    databag = state_out.get_relation(relation.id).local_app_data
    assert databag.get("username", "") == ""
    assert databag.get("password", "") == ""
    assert databag["secret-id"] == _owned_secret(state_out).id


def test_a_follower_does_not_publish(ctx):
    # GIVEN we are not the leader
    relation = testing.Relation("grafana-cloud-config")
    state_in = testing.State(
        relations={relation},
        config=dict(URLS, username="a-username", password="a-password"),
    )

    # WHEN the relation is joined
    state_out = ctx.run(ctx.on.relation_joined(relation), state_in)

    # THEN nothing is written and no secret is created
    assert _find_owned_secret(state_out) is None
    assert state_out.get_relation(relation.id).local_app_data == {}


def test_credentials_come_from_a_user_secret(ctx):
    # GIVEN a user secret granted to us and named by the credentials option
    user_secret = testing.Secret({"username": "secret-user", "password": "secret-pass"})
    relation = testing.Relation("grafana-cloud-config")
    state_in = testing.State(
        leader=True,
        relations={relation},
        secrets={user_secret},
        config=dict(URLS, credentials=user_secret.id),
    )

    # WHEN the relation is joined
    state_out = ctx.run(ctx.on.relation_joined(relation), state_in)

    # THEN the credentials from the user secret are the ones we share
    assert _owned_secret(state_out).tracked_content == {
        "username": "secret-user",
        "password": "secret-pass",
    }


def test_the_user_secret_wins_over_the_deprecated_options(ctx):
    # GIVEN both a user secret and the deprecated options
    user_secret = testing.Secret({"username": "secret-user", "password": "secret-pass"})
    relation = testing.Relation("grafana-cloud-config")
    state_in = testing.State(
        leader=True,
        relations={relation},
        secrets={user_secret},
        config=dict(
            URLS,
            credentials=user_secret.id,
            username="config-user",
            password="config-pass",
        ),
    )

    # WHEN the relation is joined
    state_out = ctx.run(ctx.on.relation_joined(relation), state_in)

    # THEN the user secret wins
    assert _owned_secret(state_out).tracked_content["username"] == "secret-user"


def test_an_unreadable_user_secret_blocks(ctx):
    # GIVEN the credentials option names a secret we cannot read
    state_in = testing.State(
        leader=True, config=dict(URLS, credentials="secret:cvh7kruupa1s46bqvuig")
    )

    # WHEN the status is collected
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # THEN the charm says so
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert "does not exist" in state_out.unit_status.message


def test_an_incomplete_user_secret_blocks(ctx):
    # GIVEN a user secret with no password
    user_secret = testing.Secret({"username": "secret-user"})
    state_in = testing.State(
        leader=True, secrets={user_secret}, config=dict(URLS, credentials=user_secret.id)
    )

    # WHEN the status is collected
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # THEN the charm names what is missing
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert "password" in state_out.unit_status.message


def test_a_new_user_secret_revision_is_published(ctx):
    # GIVEN a user secret with a newer revision than the one we track
    user_secret = testing.Secret(
        tracked_content={"username": "old-user", "password": "old-pass"},
        latest_content={"username": "new-user", "password": "new-pass"},
        label=USER_SECRET_LABEL,
    )
    relation = testing.Relation("grafana-cloud-config")
    state_in = testing.State(
        leader=True,
        relations={relation},
        secrets={user_secret},
        config=dict(URLS, credentials=user_secret.id),
    )

    # WHEN we are told the secret changed
    state_out = ctx.run(ctx.on.secret_changed(user_secret), state_in)

    # THEN the new revision is what we share
    assert _owned_secret(state_out).tracked_content == {
        "username": "new-user",
        "password": "new-pass",
    }


def test_an_unrelated_secret_changing_is_ignored(ctx):
    # GIVEN some other charm's secret
    other = testing.Secret({"key": "value"}, label="not-ours")
    state_in = testing.State(leader=True, secrets={other}, config=dict(URLS))

    # WHEN it changes
    state_out = ctx.run(ctx.on.secret_changed(other), state_in)

    # THEN nothing happens
    assert _find_owned_secret(state_out) is None


def test_old_revisions_are_removed(ctx):
    # GIVEN a secret we own
    secret = testing.Secret(
        {"username": "a-username", "password": "a-password"},
        owner="app",
        label=CREDENTIALS_SECRET_LABEL,
    )
    state_in = testing.State(leader=True, secrets={secret}, config=dict(URLS))

    # WHEN Juju tells us an older revision is no longer tracked
    old_revision = 42
    ctx.run(ctx.on.secret_remove(secret, revision=old_revision), state_in)

    # THEN we remove it
    assert ctx.removed_secret_revisions == [old_revision]


def test_another_charms_revision_is_not_removed(ctx):
    # GIVEN a secret of ours that is not the credentials one
    secret = testing.Secret({"key": "value"}, owner="app", label="not-ours")
    state_in = testing.State(leader=True, secrets={secret}, config=dict(URLS))

    # WHEN Juju tells us one of its revisions can go
    ctx.run(ctx.on.secret_remove(secret, revision=42), state_in)

    # THEN we leave it alone
    assert ctx.removed_secret_revisions == []


def test_withdrawn_credentials_are_removed(ctx):
    # GIVEN we have shared credentials, and the administrator has now cleared them
    secret = testing.Secret(
        {"username": "a-username", "password": "a-password"},
        owner="app",
        label=CREDENTIALS_SECRET_LABEL,
    )
    relation = testing.Relation("grafana-cloud-config", local_app_data={"secret-id": secret.id})
    state_in = testing.State(
        leader=True, relations={relation}, secrets={secret}, config=dict(URLS)
    )

    # WHEN the charm next publishes
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    # THEN the secret is gone, and so is the reference to it
    assert _find_owned_secret(state_out) is None
    assert state_out.get_relation(relation.id).local_app_data.get("secret-id", "") == ""
