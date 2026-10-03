"""
The core paths call into character knowledge only for stored data, readers and
the few references the decoupling keeps; knowledge reacts to core events.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "talemate"

# module -> the knowledge names it may import, each with a reason in the PR
ALLOWED = {
    "tale_mate.py": {
        "talemate.knowledge.presence.presence_metadata",
        "talemate.knowledge.perspective_models.SceneKnowledge",
        "talemate.knowledge.perspectives.bind_message_source",
        "talemate.knowledge.mode.KnowledgeEligibility",
        "talemate.knowledge.transitions.DEPARTURES_KEY",
        "talemate.knowledge.transitions.departures",
    },
    "scene_message.py": {
        "talemate.knowledge.perspective_models.PerspectiveSourceModel",
        "talemate.knowledge.transitions.transition_in_context",
        "talemate.knowledge.transitions.render_transition",
    },
    "history.py": {
        "talemate.knowledge.perspective_models.PerspectiveSourceModel",
        "talemate.knowledge.timeline.shift_world_entry_times",
        "talemate.knowledge.revision_refresh.revisions_before_rebuild",
        "talemate.knowledge.revision_refresh.settle_revisions_after_rebuild",
        "talemate.knowledge.revision_refresh.capture_revision_mutations",
    },
    "character.py": {
        "talemate.knowledge.transitions.record_departure",
        "talemate.knowledge.transitions.record_arrival",
        "talemate.knowledge.schema.EntryVisibility",
        "talemate.knowledge.schema.ReinforcementEntry",
        "talemate.knowledge.schema.is_memory_attribute",
    },
    "regenerate.py": set(),
    "agents/narrator/__init__.py": set(),
    "agents/conversation/__init__.py": {
        "talemate.knowledge.bucket.KnowledgeIndex",
    },
    "agents/editor/__init__.py": {
        "talemate.knowledge.mode.character_knowledge_enabled",
    },
    "game/engine/nodes/scene.py": set(),
    "world_state/__init__.py": {
        "talemate.knowledge.schema.EntryVisibility",
        "talemate.knowledge.schema.KnowledgeEdge",
        "talemate.knowledge.schema.ReinforcementEntry",
        "talemate.knowledge.mode.character_knowledge_enabled",
        "talemate.knowledge.snapshot_models.SnapshotPerspectives",
        "talemate.knowledge.snapshots.snapshot_for",
        "talemate.knowledge.reinforcements.reinforcement_context",
        "talemate.knowledge.reinforcements.entry_binding",
        "talemate.knowledge.reinforcements.reinforcement_entry_context",
        "talemate.knowledge.reinforcements.prepare_reinforcement_sources",
        "talemate.knowledge.reinforcements.prepare_reinforcement_source",
        "talemate.knowledge.reinforcements.write_reinforcement_entry",
    },
}


def knowledge_imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "talemate.knowledge"
        ):
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(
                alias.name
                for alias in node.names
                if alias.name.startswith("talemate.knowledge")
            )
    return names


@pytest.mark.parametrize("module", sorted(ALLOWED))
def test_core_module_imports_only_the_listed_knowledge_names(module):
    assert knowledge_imports(SRC / module) <= ALLOWED[module]


def test_no_generation_entry_point_runs_the_knowledge_step_itself():
    for module in ALLOWED:
        assert "knowledge_step" not in (SRC / module).read_text(), module
