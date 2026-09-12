# Test fixtures and provider boundaries

Provision from the project root with `uv sync --extra dev --locked`. Run the
complete Python suite with `uv run pytest tests/`. Tests use `config.example.yaml`
and redirect configuration writes to a temporary directory; never copy or change
the active `config.yaml` for a test run. Compose rendering tests require the Docker
Compose CLI, without a daemon. The default suite includes them.

## Scene file persistence

Use the opt-in `persistence_scene_factory` from [conftest.py](conftest.py) for
real scene JSON save/reload checks. It confines the scene directories to pytest's
`tmp_path`, isolates global recent-scene updates, and bootstraps the existing
agent stack. Each call rebinds that stack: operate on one scene at a time, then
create a fresh instance to reload. It is not a concurrent-scene fixture.

Call `await scene.save(copy_name="copy.json")`, read `Path(scene.full_path)` with
`json.loads`, then call `await load_scene_from_data(fresh, saved_data,
name=str(saved_path))`. Supply `reset=True` only when testing restart semantics:
it deliberately clears history and does not restore saved world state.

[test_scene_persistence_fixture.py](test_scene_persistence_fixture.py) exercises
save-as, actual serialization and disk reads, fresh-instance canonical reload,
history reset, empty-pin cleanup and a second saved copy. The JSON/PNG import
round trips in [test_character_card_extraction_options.py](test_character_card_extraction_options.py)
also use this fixture. Keep their persisted-content assertions on real files;
do not stub `Scene.save`, `serialize`, `commit_to_memory`, `load_scene_from_data`
or pin cleanup to repair a missing mock method.

`MockMemoryAgent` has empty, non-persistent storage: writes/drop/close/setup are
no-ops, and document lookup returns an empty mapping. Missing-memory pins therefore
disappear on real cleanup. This fixture proves scene **file** persistence, not
embedding/database persistence or retention of populated memory pins. For those,
use a focused memory-agent fixture such as [test_memory_set_db_race.py](test_memory_set_db_race.py).

## Shared client lifecycle changes

Reuse the focused examples in [test_prompt_lifecycle.py](test_prompt_lifecycle.py)
and build the matrix from the provider execution paths the change affects:

| Boundary | Existing test | What the test actually exercises |
| --- | --- | --- |
| Async overlap | `test_same_client_overlap_keeps_usage_reasoning_and_identity` | Real `send_prompt`, controlled async provider completion in reverse order, independent metadata |
| Executor overlap | `test_executor_streams_keep_request_metadata_under_overlap` | Actual TextGen chat/completion and KoboldCpp worker loops, substituted HTTP/SSE transport, thread barriers and distinct request context |
| Parameters added/removed after preparation | `test_effective_provider_parameters_refresh_terminal_and_jsonl` | Real lifecycle, controlled provider mutation, terminal and JSONL equality for success/retry/failure/cancel |
| SDK request parameters | `test_anthropic_effective_parameters_match_sdk_request` | Real Anthropic provider method, substituted SDK boundary, emitted effective parameters compared to actual captured SDK arguments |
| Terminal cleanup | `test_terminal_outcomes`, `test_task_cancellation_cleans_up_provider_and_emits_terminal`, `test_retry_success_updates_one_logical_record` | Terminal event count/identity, cancellation cleanup and retry accounting |

Provide synthetic inputs for every local guard (including the explicit fake
Anthropic credential), substitute transport before sending, and make unexpected
provider errors fail immediately. Use bounded waits and release worker barriers
in `finally`. Assert the worker finished as well as the unwanted behavior being
absent. Compare a copied SDK payload to the terminal record so later mutation
cannot make the comparison vacuous. Keep the earlier active snapshot unchanged.

Run these boundaries offline with `uv run --no-sync pytest
tests/test_prompt_lifecycle.py`. These are controlled provider-boundary tests,
not paid live provider coverage. A browser test with one provider cannot establish
executor or other provider behavior. Real provider checks need their own scope,
authorization and evidence; a generic framework is unnecessary here.
