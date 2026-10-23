import json
import os
from pathlib import Path

import pytest

from talemate.world_state.templates.base import (
    TEMPLATE_PATH_TALEMATE,
    Collection,
    Group,
)
from talemate.world_state.templates.content import WritingStyle
from talemate.world_state.templates.decision_checks import (
    default_writing_style_decision_checks,
)

ADVENTURE_GAME = "0802e774-74d5-4d41-9e7a-78744e66f09e"
POLISHED_PROSE = "ffecb67e-34fe-4aa7-818b-d3270c8e2610"
SCENES = Path(__file__).resolve().parents[1] / "scenes"


@pytest.fixture(scope="module")
def default_group() -> Group:
    return Group.load(os.path.join(TEMPLATE_PATH_TALEMATE, "default.yaml"))


@pytest.mark.parametrize(
    "uid, name",
    [(ADVENTURE_GAME, "Adventure Game"), (POLISHED_PROSE, "Polished Prose")],
)
def test_shipped_writing_style_loads(default_group, uid, name):
    style = default_group.templates[uid]
    assert isinstance(style, WritingStyle)
    assert style.name == name
    assert style.instructions and style.description
    assert style.phrases == []


@pytest.mark.parametrize("uid", [ADVENTURE_GAME, POLISHED_PROSE])
def test_shipped_writing_style_stores_current_default_checks(default_group, uid):
    # default.yaml stores a copy; refresh it whenever the defaults change
    assert [
        check.model_dump() for check in default_group.templates[uid].decision_checks
    ] == [check.model_dump() for check in default_writing_style_decision_checks()]


@pytest.mark.parametrize(
    "scene_file",
    [
        "infinity-quest/infinity-quest.json",
        "infinity-quest-dynamic-scenario/infinity-quest.json",
        "infinity-quest-dynamic-story-v2/infinity-quest.json",
        "simulation-suite/simulation-suite.json",
        "simulation-suite-v2/the-simulation-suite.json",
    ],
)
def test_shipped_scene_uses_polished_prose(default_group, scene_file):
    data = json.loads((SCENES / scene_file).read_text())
    style = Collection(groups=[default_group]).find_template_by_id(
        data["writing_style_template"]
    )
    assert style is default_group.templates[POLISHED_PROSE]
