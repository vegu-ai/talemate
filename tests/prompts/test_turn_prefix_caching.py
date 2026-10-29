"""Offline, two-turn prefix benchmark for the normal direction pipeline.

Run with -s to print character-prefix shares (not provider cache-hit rates).
History grows by one message; current memory, state, instructions and call
budgets change. Both layouts must retain the same non-whitespace content.
"""

from collections import Counter
from os.path import commonprefix
import random
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from talemate.agents.director.action_core.schema import (
    ActionCoreFunctionAvailable,
)
from talemate.agents.director.scene_direction.schema import SceneDirectionBudgets
from talemate.game.focal import Focal, Callback, Argument
from talemate.prompts import Prompt
from talemate.world_state import Reinforcement
from .helpers import create_scene_with_characters

TEMPLATES = [
    "director.scene-direction",
    "director.chat-execute-actions",
    "common.base",
    "conversation.dialogue-narrative",
    "editor.unslop",
    "editor.unslop-narration",
    "director.guide-narration",
    "summarizer.analyze-scene-for-next-narration",
    "world_state.update-reinforcements",
]


def render_turn(
    template, optimized, turn, history_length=30, callback_names=("direct_scene",)
):
    scene = create_scene_with_characters()
    lines = [
        f'Elena: "At marker {i}, I found {i + 2} fresh tracks beside the river. '
        f'The traveler carrying parcel {i + 10} went toward the ruined bridge."'
        for i in range(history_length + turn)
    ]
    scene.context_history = Mock(return_value=lines)
    scene.get_intro = Mock(return_value=scene.intro)
    scene.world_state.reinforce.append(
        Reinforcement(
            question="Current lead", answer=f"LEAD-{turn}", insert="all-context"
        )
    )
    character = scene.get_character("Elena")
    character.example_dialogue = [
        f'Elena: "Listen to the {word}."'
        for word in ["wind", "river", "birds", "rain", "leaves", "footsteps"]
    ]
    callbacks = [
        Callback(
            name=name,
            arguments=[Argument(name="instructions", type="str")],
            fn=Mock(),
        )
        for name in callback_names
    ]
    focal = Focal(client=Mock(), callbacks=callbacks, max_calls=2 + turn)
    focal.state.schema_format = "json"

    def action(agent, name, **kwargs):
        if name == "guidance_context":
            return [
                SimpleNamespace(
                    character="Elena",
                    unavailable=False,
                    authored=[
                        SimpleNamespace(
                            label=None,
                            text="Elena keeps the ferry ledger.",
                            reinforcement=False,
                        ),
                        SimpleNamespace(
                            label=None, text=f"NOTE-{turn}", reinforcement=True
                        ),
                    ],
                    history=[f"EVIDENCE-{turn}"],
                    snapshot={"lead": f"LEAD-{turn}"},
                )
            ]
        if name == "history_context":
            return list(lines)
        if name == "rag_exclude_context_history":
            return kwargs["context"]
        if name.startswith("rag_build"):
            return [f"MEMORY-{turn}: The ferryman remembers the sealed parcel."]
        return None

    vars = dict(
        scene=scene,
        max_tokens=32000,
        reserved_tokens=300,
        volatile_context_placement=lambda: (
            "after_history" if optimized else "before_history"
        ),
        character_knowledge_enabled=lambda scene: template.startswith("director.")
        or template.startswith("summarizer."),
        agent_action=action,
        agent_config=lambda path: False,
        active_agent=SimpleNamespace(
            agent=SimpleNamespace(agent_type="director"), state={}
        ),
        agent_context_state={},
        knowledge_index=SimpleNamespace(
            sheet=lambda s, c, *a: c.sheet_filtered("description"),
            description=lambda s, c, *a: c.description,
            knows_entry=lambda *a: True,
        ),
        characters=scene.characters,
        talking_character=character,
        character=character,
        formatted_names="Hero",
        actor_instructions_offset=0,
        actor_instructions="Keep Elena's reserved voice.",
        direct_instruction=f"DIRECTION-{turn}",
        revision_context_history=lambda *a, **kw: lines,
        text=(
            f"DRAFT-{turn}: Elena examined the parcel."
            if template.startswith("editor.")
            else ""
        ),
        repetition=[] if turn == 0 else [{"text_a": "Elena examined the parcel."}],
        repetition_handling="remove",
        scene_analysis=f"ANALYSIS-{turn}",
        analysis=f"ANALYSIS-{turn}",
        response_length=256,
        length=512,
        deep_analysis=False,
        combined_guidance_instructions="",
        decensor=False,
        query_memory=lambda *a, **kw: "Elena is reserved and exact.",
        question="What is Elena's current mood?",
        reinforcement=SimpleNamespace(insert="all-context"),
        budgets=SceneDirectionBudgets(max_tokens=32000, scene_context_ratio=0.3),
        direction_history_trim=lambda history, budget: history,
        trim_action_history=lambda history, budget: history,
        history=[
            SimpleNamespace(type="text", source="director", message=line)
            for line in lines
        ],
        available_functions=[
            ActionCoreFunctionAvailable(
                name="direct_scene",
                description="Direct characters and narration without controlling the player.",
            )
        ],
        direction_enable_analysis=True,
        gamestate={"turn": turn},
        custom_instructions=f"CUSTOM-{turn}",
        useful_context_ids={},
        maintain_turn_balance=True,
        turn_balance=SimpleNamespace(
            total_messages_analyzed=30 + turn,
            narrator_message_count=0,
            character_message_counts={"Elena": 30 + turn},
            character_percentages={"Elena": 100},
            neglected_characters=[],
        ),
        user_agency=SimpleNamespace(should_remind=True, director_turn_count=2 + turn),
        focal=focal,
        callbacks_unique=callbacks,
        has_character_callback=True,
        ordered_instructions={},
        ordered_examples={},
        ordered_argument_usage={},
        selections=[
            SimpleNamespace(name=name, instructions=f"SELECTED-{turn}-{name}")
            for name in callback_names
        ],
        include_scene_intent=True,
        include_character_context=True,
        include_scene_context=True,
        include_memory_context=True,
        include_extra_context=True,
        include_gamestate_context=True,
        dynamic_context=[f"DYNAMIC-{turn}"],
        instructions=f"TASK-{turn}",
    )
    prompt = Prompt.get(template, vars=vars)
    # Director, Focal and Editor explicitly disable deduplication; Conversation
    # follows the client default (also off). Retain all fragments for comparison.
    prompt.dedupe_enabled = False
    random_state = random.getstate()
    try:
        random.seed(40 + turn)
        return prompt.render()
    finally:
        random.setstate(random_state)


@pytest.mark.parametrize("template", TEMPLATES)
def test_two_turn_prefix_and_content(template):
    old = [render_turn(template, False, turn) for turn in (0, 1)]
    new = [render_turn(template, True, turn) for turn in (0, 1)]
    for before, after in zip(old, new):
        # Reordering must retain every word, including section headings.
        assert Counter(before.split()) == Counter(after.split())
    old_prefix = len(commonprefix(old))
    new_prefix = len(commonprefix(new))
    print(
        f"{template}: {old_prefix}/{len(old[1])} ({old_prefix / len(old[1]):.1%})"
        f" -> {new_prefix}/{len(new[1])} ({new_prefix / len(new[1]):.1%})"
    )
    # A third request can reuse the entire common prefix found in the first two.
    assert render_turn(template, True, 2).startswith(commonprefix(new))
    assert new_prefix > old_prefix
    assert new_prefix / len(new[1]) > 0.4
    assert "At marker 29, I found 31 fresh tracks" in commonprefix(new)
    assert "marker 30," not in new[0]
    assert "marker 30," in new[1]


def test_short_conversation_keeps_current_guidance_after_history():
    prompt = render_turn("conversation.dialogue-narrative", True, 1, history_length=3)
    assert prompt.index("marker 3,") < prompt.index("DIRECTION-1")
    assert prompt.index("marker 3,") < prompt.index("MEMORY-1")
    assert prompt.index("marker 3,") < prompt.index("LEAD-1")
    assert "Keep Elena's reserved voice." in prompt


@pytest.mark.parametrize("template", ["common.base", "director.chat-execute-actions"])
def test_schema_order_is_stable_but_execution_order_is_preserved(template):
    names = ("direct_scene", "query_world")
    first = render_turn(template, True, 0, callback_names=names)
    second = render_turn(template, True, 1, callback_names=names[::-1])
    prefix = commonprefix([first, second])
    if template == "director.chat-execute-actions":
        # The action history leads; the schemas follow it in a fixed order.
        assert "marker 29," in prefix
        assert second.index("direct_scene arguments") < second.index(
            "query_world arguments"
        )
    else:
        assert "direct_scene arguments" in prefix
        assert "query_world arguments" in prefix
    assert "allowed to make up to 3 function calls" in second
    assert second.index("marker 30,") < second.index("allowed to make up to 3")
    if template == "director.chat-execute-actions":
        assert second.index("1. query_world: SELECTED-1-query_world") < second.index(
            "2. direct_scene: SELECTED-1-direct_scene"
        )


def test_direction_keeps_authored_evidence_and_history_in_prefix():
    turns = [render_turn("director.scene-direction", True, turn) for turn in (0, 1)]
    prefix = commonprefix(turns)
    # The scene leads: it only grows at its tail and is by far the largest
    # block. Authored evidence, intent and pins change every few turns and
    # follow it, then the direction history, then the per-turn context.
    assert "## Scene\n" in prefix
    assert "NOTE-0" not in prefix
    assert "EVIDENCE-0" not in prefix
    assert "CUSTOM-0" not in prefix
    second = turns[1]
    assert second.index("## Scene\n") < second.index("Elena keeps the ferry ledger.")
    assert second.index("Elena keeps the ferry ledger.") < second.index(
        "## Direction history"
    )
    assert second.index("## Direction history") < second.index("NOTE-1")
    assert second.index("NOTE-1") < second.index("REMINDER: You are the Director")


def test_execution_prefix_survives_changing_function_selection():
    first = render_turn(
        "director.chat-execute-actions",
        True,
        0,
        callback_names=("direct_scene", "yield_to_user"),
    )
    second = render_turn("director.chat-execute-actions", True, 1)
    prefix = commonprefix([first, second])
    assert "marker 29," in prefix
    assert "yield_to_user" not in prefix
