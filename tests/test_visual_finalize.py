import pytest
import yaml

import talemate.agents.visual.finalize as finalize
from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.finalize import (
    apply_exact,
    apply_fuzzy,
    apply_regex,
    cleanup_prompt,
    validate_finalizers,
)
from talemate.agents.visual.schema import (
    FINALIZER_MODE,
    FINALIZER_TARGET,
    VIS_TYPE,
    GenerationRequest,
    PromptFinalizer,
)
from talemate.character import Character


def test_cleanup_prompt():
    assert cleanup_prompt("a, , b") == "a, b"
    assert cleanup_prompt(", a, b, ") == "a, b"
    assert cleanup_prompt("a,  b") == "a, b"
    assert cleanup_prompt("a ,b") == "a,b"


class TestApplyExact:
    def test_case_insensitive_by_default(self):
        assert (
            apply_exact("Red hair, green eyes", "red hair", "crimson hair", False)
            == "crimson hair, green eyes"
        )

    def test_case_sensitive(self):
        text = "Red hair, red hair"
        assert apply_exact(text, "red hair", "crimson hair", True) == (
            "Red hair, crimson hair"
        )

    def test_no_match_returns_original(self):
        text = "green eyes"
        assert apply_exact(text, "red hair", "crimson hair", False) is text

    def test_empty_replacement_removes_and_cleans_up(self):
        assert (
            apply_exact("a woman, red hair, green eyes", "red hair", "", False)
            == "a woman, green eyes"
        )

    def test_empty_match_is_noop(self):
        assert apply_exact("a woman", "", "x", False) == "a woman"

    def test_replacement_with_backslash_is_literal(self):
        assert apply_exact("a woman", "woman", r"wo\man", False) == r"a wo\man"


class TestApplyFuzzy:
    def test_replaces_similar_segment(self):
        assert (
            apply_fuzzy(
                "masterpiece, red haired, 1girl", "red hair", "crimson hair", 85
            )
            == "masterpiece, crimson hair, 1girl"
        )

    def test_case_insensitive(self):
        assert (
            apply_fuzzy("Red Hair, 1girl", "red hair", "crimson hair", 85)
            == "crimson hair, 1girl"
        )

    def test_empty_replacement_removes_segment(self):
        assert apply_fuzzy("a, red hair, b", "red hair", "", 85) == "a, b"

    def test_below_threshold_untouched(self):
        text = "masterpiece, blue dress"
        assert apply_fuzzy(text, "red hair", "crimson hair", 85) is text

    def test_empty_match_is_noop(self):
        text = "a, b"
        assert apply_fuzzy(text, "  ", "x", 85) is text


class TestApplyRegex:
    def test_group_passthrough(self):
        assert (
            apply_regex(
                "bright blue eyes", r"bright (\w+) eyes", r"glowing \1 eyes", []
            )
            == "glowing blue eyes"
        )

    def test_case_sensitive_flag(self):
        text = "Blue eyes"
        assert apply_regex(text, r"blue", "green", ["case_sensitive"]) is text
        assert apply_regex(text, r"blue", "green", []) == "green eyes"

    def test_invalid_pattern_returns_original(self):
        text = "a, b"
        assert apply_regex(text, r"(unclosed", "x", []) is text

    def test_empty_replacement_cleans_up(self):
        assert apply_regex("a, red hair, b", r"red \w+", "", []) == "a, b"


def test_validate_finalizers_skips_invalid_rows():
    rows = [
        {"mode": "EXACT", "match": "a", "replace": "b"},
        {"mode": "NOT_A_MODE"},
        "not a dict",
        PromptFinalizer(mode=FINALIZER_MODE.REGEX, match="x"),
    ]
    finalizers = validate_finalizers(rows)
    assert len(finalizers) == 2
    assert finalizers[0].mode == FINALIZER_MODE.EXACT
    assert finalizers[1].mode == FINALIZER_MODE.REGEX


def test_finalizer_is_yaml_safe():
    # finalizers are stored inside world state template groups, which
    # are persisted with yaml.dump and reloaded with yaml.safe_load
    finalizer = PromptFinalizer(
        mode=FINALIZER_MODE.AI,
        target=FINALIZER_TARGET.BOTH,
        vis_types=[VIS_TYPE.CHARACTER_PORTRAIT],
        flags=["case_sensitive"],
    )
    dumped = yaml.dump(finalizer.model_dump())
    assert "python/object" not in dumped
    assert PromptFinalizer(**yaml.safe_load(dumped)) == finalizer


class TestAppliesTo:
    def test_disabled(self):
        finalizer = PromptFinalizer(enabled=False)
        assert not finalizer.applies_to(VIS_TYPE.UNSPECIFIED, True)

    def test_vis_type_filter(self):
        finalizer = PromptFinalizer(vis_types=[VIS_TYPE.CHARACTER_PORTRAIT.value])
        assert finalizer.applies_to(VIS_TYPE.CHARACTER_PORTRAIT, True)
        assert not finalizer.applies_to(VIS_TYPE.SCENE_BACKGROUND, True)

    def test_empty_vis_types_applies_to_all(self):
        finalizer = PromptFinalizer()
        assert finalizer.applies_to(VIS_TYPE.SCENE_BACKGROUND, True)

    def test_target(self):
        positive = PromptFinalizer(target=FINALIZER_TARGET.POSITIVE)
        negative = PromptFinalizer(target=FINALIZER_TARGET.NEGATIVE)
        both = PromptFinalizer(target=FINALIZER_TARGET.BOTH)
        assert positive.applies_to(VIS_TYPE.UNSPECIFIED, True)
        assert not positive.applies_to(VIS_TYPE.UNSPECIFIED, False)
        assert not negative.applies_to(VIS_TYPE.UNSPECIFIED, True)
        assert negative.applies_to(VIS_TYPE.UNSPECIFIED, False)
        assert both.applies_to(VIS_TYPE.UNSPECIFIED, True)
        assert both.applies_to(VIS_TYPE.UNSPECIFIED, False)


class FakeScene:
    def __init__(self, characters=None):
        self.characters = characters or {}
        self.agent_overrides = None

    def get_character(self, name):
        return self.characters.get(name)


@pytest.fixture
def agent():
    agent = VisualAgent()
    return agent


def set_finalizers(agent, rows):
    agent.actions["_prompt_finalization"].config["finalizers"].value = rows


class TestFinalizePromptRequest:
    async def test_disabled_leaves_request_untouched(self, agent):
        agent.actions["_prompt_finalization"].enabled = False
        set_finalizers(agent, [{"mode": "EXACT", "match": "a", "replace": "b"}])
        request = GenerationRequest(prompt="a")
        await agent.finalize_prompt_request(request)
        assert request.prompt == "a"

    async def test_exact_and_regex_in_order(self, agent):
        set_finalizers(
            agent,
            [
                {"mode": "EXACT", "match": "red hair", "replace": "crimson hair"},
                {
                    "mode": "REGEX",
                    "match": r"crimson (\w+)",
                    "replace": r"dark crimson \1",
                },
            ],
        )
        request = GenerationRequest(prompt="a woman, red hair")
        await agent.finalize_prompt_request(request)
        assert request.prompt == "a woman, dark crimson hair"

    async def test_negative_prompt_target(self, agent):
        set_finalizers(
            agent,
            [
                {
                    "mode": "EXACT",
                    "match": "blurry",
                    "replace": "blurry, low quality",
                    "target": "NEGATIVE",
                }
            ],
        )
        request = GenerationRequest(prompt="blurry photo", negative_prompt="blurry")
        await agent.finalize_prompt_request(request)
        assert request.prompt == "blurry photo"
        assert request.negative_prompt == "blurry, low quality"

    async def test_vis_type_filter(self, agent):
        set_finalizers(
            agent,
            [
                {
                    "mode": "EXACT",
                    "match": "red",
                    "replace": "blue",
                    "vis_types": [VIS_TYPE.SCENE_BACKGROUND.value],
                }
            ],
        )
        request = GenerationRequest(
            prompt="red sky", vis_type=VIS_TYPE.CHARACTER_PORTRAIT
        )
        await agent.finalize_prompt_request(request)
        assert request.prompt == "red sky"

        request = GenerationRequest(
            prompt="red sky", vis_type=VIS_TYPE.SCENE_BACKGROUND
        )
        await agent.finalize_prompt_request(request)
        assert request.prompt == "blue sky"

    async def test_character_finalizers_run_after_agent_finalizers(self, agent):
        set_finalizers(
            agent,
            [{"mode": "EXACT", "match": "red hair", "replace": "crimson hair"}],
        )
        character = Character(
            name="Elena",
            visual_finalizers=[
                PromptFinalizer(
                    mode=FINALIZER_MODE.EXACT,
                    match="crimson hair",
                    replace="crimson hair with silver streaks",
                )
            ],
        )
        agent.scene = FakeScene(characters={"Elena": character})

        request = GenerationRequest(prompt="Elena, red hair", character_name="Elena")
        await agent.finalize_prompt_request(request)
        assert request.prompt == "Elena, crimson hair with silver streaks"

        # without the character the character finalizer does not run
        request = GenerationRequest(prompt="Elena, red hair")
        await agent.finalize_prompt_request(request)
        assert request.prompt == "Elena, crimson hair"

    async def test_fuzzy_threshold_config(self, agent):
        set_finalizers(
            agent, [{"mode": "FUZZY", "match": "red hair", "replace": "crimson hair"}]
        )
        agent.actions["_prompt_finalization"].config["fuzzy_threshold"].value = 100
        request = GenerationRequest(prompt="a woman, red haired")
        await agent.finalize_prompt_request(request)
        assert request.prompt == "a woman, red haired"

        agent.actions["_prompt_finalization"].config["fuzzy_threshold"].value = 85
        request = GenerationRequest(prompt="a woman, red haired")
        await agent.finalize_prompt_request(request)
        assert request.prompt == "a woman, crimson hair"

    async def test_ai_finalizer(self, agent, monkeypatch):
        set_finalizers(
            agent,
            [{"mode": "AI", "replace": "Convert the prompt to JSON."}],
        )

        captured = {}

        async def fake_request(uid, client, kind, vars=None, **kwargs):
            captured.update(uid=uid, kind=kind, vars=vars)
            # Prompt.request returns (response, extracted) - see Prompt.send
            return ('<FINALIZED_PROMPT>{"prompt": "a woman"}</FINALIZED_PROMPT>', {})

        monkeypatch.setattr(finalize.Prompt, "request", fake_request)

        class FakeClient:
            max_token_length = 8192

        agent.client = FakeClient()

        request = GenerationRequest(prompt="a woman")
        await agent.finalize_prompt_request(request)

        assert request.prompt == '{"prompt": "a woman"}'
        assert captured["uid"] == "visual.finalize-prompt"
        assert captured["vars"]["instruction"] == "Convert the prompt to JSON."

    async def test_ai_finalizer_without_client_is_noop(self, agent):
        set_finalizers(agent, [{"mode": "AI", "replace": "Convert."}])
        request = GenerationRequest(prompt="a woman")
        await agent.finalize_prompt_request(request)
        assert request.prompt == "a woman"
