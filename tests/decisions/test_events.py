from talemate.decisions.events import (
    ActionRecord,
    DecisionLog,
    InvocationRecord,
    RequestRecord,
)

from talemate.util.logging import serialize_log_value


def record(invocation_id="invocation"):
    return RequestRecord(
        invocation_id=invocation_id,
        template_uid="editor.policy",
        source_group="user",
        label="label",
        provider="fake",
        model="model",
    )


def test_active_invocations_and_actions_survive_retention_and_clear():
    log = DecisionLog(max_finished=1)
    active = record()
    active.status = "completed"
    log.start_invocation(
        InvocationRecord(id=active.invocation_id, template_uid=active.template_uid)
    )
    log.add(active)
    pending = record("pending")
    log.add(pending)
    action_entry = record("action")
    action_entry.status = "completed"
    action_entry.actions.append(ActionRecord(action="rewrite"))
    log.add(action_entry)
    old, new = record("old"), record("new")
    for entry in (old, new):
        entry.status = "completed"
        log.add(entry)
    assert list(log.records) == [active.id, pending.id, action_entry.id, new.id]
    log.clear_finished()
    assert list(log.records) == [active.id, pending.id, action_entry.id]
    log.finish_invocation(active.invocation_id, status="completed")
    log.clear_finished()
    assert list(log.records) == [pending.id, action_entry.id]
    action_entry.actions[0].status = "completed"
    log.update(action_entry)
    log.clear_finished()
    assert list(log.records) == [pending.id]


def test_default_retention_is_fifty_finished_entries():
    log = DecisionLog()
    for index in range(55):
        entry = record(str(index))
        entry.status = "completed"
        log.start_invocation(
            InvocationRecord(id=entry.invocation_id, template_uid=entry.template_uid)
        )
        log.add(entry)
        log.finish_invocation(entry.invocation_id, status="completed")
    assert len(log.records) == 50
    assert len(log.invocations) == 50
    assert set(log.invocations) == {
        entry.invocation_id for entry in log.records.values()
    }


def test_observer_snapshots_are_isolated_and_unsubscription_works():
    log = DecisionLog()
    received = []

    def corrupt(event):
        event["entry"]["state"] = "changed"
        raise RuntimeError("observer failure")

    log.subscribe(corrupt)
    unsubscribe = log.subscribe(received.append)
    entry = record()
    entry.state = {"passage": "text"}
    log.add(entry)
    entry.status = "completed"
    log.update(entry)
    assert received[0]["entry"]["status"] == "pending"
    assert received[1]["entry"]["state"] == {"passage": "text"}
    unsubscribe()
    log.update(entry)
    assert len(received) == 2


def test_runtime_objects_are_not_dumped_or_formatted():
    class SensitiveObject:
        def __repr__(self):
            raise AssertionError("repr must not be called")

        def model_dump(self):
            raise AssertionError("model_dump must not be called")

    data = serialize_log_value(
        {
            "scene": SensitiveObject(),
            "api_key": "do not retain",
            "nested": [{"override_api_key": "do not retain"}],
            "number": 42,
            "finite": 0.7,
            "not_finite": float("nan"),
        }
    )
    assert data == {
        "scene": "[runtime object omitted]",
        "api_key": "(hidden)",
        "nested": [{"override_api_key": "(hidden)"}],
        "number": 42,
        "finite": 0.7,
        "not_finite": None,
    }


def test_unset_secret_is_logged_as_none():
    assert serialize_log_value({"api_key": "", "nested": {"API_KEY": None}}) == {
        "api_key": None,
        "nested": {"API_KEY": None},
    }


def test_plain_config_and_mixed_dictionary_keys_are_preserved():
    assert serialize_log_value({"config": {"threshold": 0.8}}) == {
        "config": {"threshold": 0.8}
    }
    assert serialize_log_value({1: "integer", "1": "string"}) == {
        "entries": [{"key": 1, "value": "integer"}, {"key": "1", "value": "string"}]
    }


def test_observer_diagnostics_identify_listener_without_exception_text(monkeypatch):
    from unittest.mock import Mock
    from talemate.decisions import events

    logger = Mock()
    monkeypatch.setattr(events, "log", logger)

    def broken_observer(event):
        raise RuntimeError("private failure payload")

    log = DecisionLog()
    log.subscribe(broken_observer)
    log.add(record())
    logger.warning.assert_called_once_with(
        "decision_log_listener_failed",
        listener=broken_observer.__qualname__,
        error_type="RuntimeError",
    )


def test_finishing_a_cancelled_request_does_not_invent_an_outcome():
    log = DecisionLog()
    entry = record()
    entry.status = "cancelled"
    log.start_invocation(
        InvocationRecord(id=entry.invocation_id, template_uid=entry.template_uid)
    )
    log.add(entry)
    log.finish_invocation(entry.invocation_id, status="cancelled")
    assert entry.outcomes == []


def test_invocation_metadata_survives_until_its_last_request_is_removed():
    log = DecisionLog(max_finished=1)
    log.start_invocation(InvocationRecord(id="shared", template_uid="editor.policy"))
    first, second = record("shared"), record("shared")
    for entry in (first, second):
        entry.status = "completed"
        log.add(entry)
    assert len(log.records) == 2
    log.finish_invocation("shared", status="completed")
    assert list(log.records) == [second.id]
    assert log.invocations["shared"].request_count == 2
    removed = []
    log.subscribe(removed.append)
    log.clear_finished()
    assert log.snapshot() == {"requests": [], "invocations": []}
    assert removed == [
        {"event": "removed", "request_ids": [second.id], "invocation_ids": ["shared"]}
    ]


def test_standalone_invocations_share_the_finished_entry_budget():
    log = DecisionLog(max_finished=2)
    entry = record()
    entry.status = "completed"
    log.start_invocation(
        InvocationRecord(id=entry.invocation_id, template_uid=entry.template_uid)
    )
    log.add(entry)
    log.finish_invocation(entry.invocation_id, status="completed")
    for key in ("standalone1", "standalone2"):
        invocation = InvocationRecord(
            id=key,
            template_uid="editor.policy",
            actions=[ActionRecord(action="rewrite", status="completed")],
        )
        log.start_invocation(invocation)
        log.finish_invocation(key, status="completed")
    assert not log.records
    assert list(log.invocations) == ["standalone1", "standalone2"]
    log.clear_finished()
    assert log.snapshot() == {"requests": [], "invocations": []}


def test_active_and_pending_standalone_invocations_survive_clearing_and_pruning():
    log = DecisionLog(max_finished=0)
    invocation = InvocationRecord(id="standalone", template_uid="editor.policy")
    log.start_invocation(invocation)
    log.clear_finished()
    assert list(log.invocations) == [invocation.id]
    action = ActionRecord(action="rewrite")
    invocation.actions.append(action)
    log.finish_invocation(invocation.id, status="completed")
    log.clear_finished()
    assert list(log.invocations) == [invocation.id]
    action.status = "completed"
    log.clear_finished()
    assert not log.invocations
