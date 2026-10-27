"""Help must retain existing routes when decision settings are indexed."""

import pytest

from talemate.agents.help import docs


# Limits retain the pre-decision-summary ranks, including broader queries whose
# settings page already followed a dedicated guide or node reference.
EXISTING_TOPICS = {
    "user-guide/agents/memory/settings.md": [
        ("select embeddings", 4),
        ("switch CPU CUDA devices", 1),
        ("recency weight", 1),
        ("diversity threshold", 1),
        ("entity descriptions", 3),
        ("local cross-encoder reranking", 1),
        ("memory retrieval no text-generation requests", 3),
    ],
    "user-guide/agents/world-state/settings.md": [
        ("snapshot frequency", 2),
        ("Lines in the moment", 1),
        ("Look at Add Detail highlights", 1),
        ("context pinning", 1),
        ("durable snapshots eviction", 2),
        ("state reinforcements", 6),
        ("conditional pins", 3),
        ("character progression proposals", 1),
        ("tagged portrait selection generation", 1),
        ("semantic long-term memory", 2),
    ],
    "user-guide/app-settings/decision-model.md": [
        ("Opt-in decisions send scene text", 1),
        ("provider model ID shared API key", 2),
        ("request deadline without retry", 3),
        ("green dot Configured", 1),
        ("Configured setup not key test", 7),
        ("Off Incomplete failure banners", 1),
        ("Request not sent", 2),
        ("oversize input conservative token estimates", 1),
        ("max_input_tokens", 2),
        ("max_question_input_tokens", 2),
        ("input_token_multiplier", 2),
        ("zero limit undeclared", 2),
    ],
    "user-guide/node-editor/reference/nodes/agents-world-state.md": [
        ("time advancement chapter titles", 2),
        ("character progression suggestions", 2),
        ("presence checks", 2),
        ("sheet extraction", 3),
        ("tracked State Reinforcement", 6),
        ("Evaluate Query", 1),
        ("Request Emit World State", 1),
        ("avatar selection", 2),
        ("deactivation websocket handlers sockets properties", 2),
    ],
}

DECISION_TOPICS = {
    "user-guide/agents/memory/settings.md": [
        ("Use Decision Model for Entity Lookup", 2),
        ("entity lookup pronoun title nickname", 1),
        ("entity lookup name match fallback", 1),
    ],
    "user-guide/agents/world-state/settings.md": [
        ("decision model tracked state no change", 5),
        ("decision model snapshot audiences", 3),
        ("decision model conditional pins", 5),
        ("decision model yes/no queries", 2),
        ("tracked state no change skipped", 4),
        ("character portraits decision model settings", 2),
    ],
    "user-guide/app-settings/decision-model.md": [
        ("decision model default-on World State Memory", 1),
        ("decision model Editor checks separate opt-in", 1),
        ("green dot", 1),
        ("token estimates", 1),
        ("hosted TypeSafe decision model base URL", 1),
        ("SystemOne API server", 1),
        ("local SystemOne base URL", 1),
        ("decision model optional API key", 1),
        ("Von Kev calibration", 1),
        ("decision model input limits", 1),
        ("decision model shared OpenRouter key", 5),
    ],
    "user-guide/node-editor/reference/nodes/agents-world-state.md": [
        ("Evaluate Query decision model fallback", 3),
        ("Determine Avatar decision model fallback", 3),
    ],
}


@pytest.mark.parametrize(
    "page,query,limit",
    [
        (page, query, limit)
        for topics in (EXISTING_TOPICS, DECISION_TOPICS)
        for page, queries in topics.items()
        for query, limit in queries
    ],
)
def test_decision_settings_keep_help_routes(page, query, limit):
    assert page in [entry["path"] for entry in docs.find_docs(query, limit=limit)]
