import json
import pathlib
from types import SimpleNamespace

import pytest

from talemate.prompts import Prompt

TEMPLATE = "visual.refine-prompt"


def asset(analysis=None, tags=None):
    return SimpleNamespace(meta=SimpleNamespace(analysis=analysis, tags=tags or []))


def render(assets):
    return Prompt.get(
        TEMPLATE,
        vars={
            "assets": assets,
            "gathered_information": "",
            "instructions": "",
            "visual_prompt": SimpleNamespace(
                positive_prompt_descriptive="Elena in a tavern"
            ),
            "max_tokens": 4096,
        },
    ).render()


@pytest.fixture
def one_reference():
    return render([asset(analysis="a tall woman with red hair")])


@pytest.fixture
def two_references():
    return render(
        [
            asset(analysis="a tall woman with red hair"),
            asset(analysis="an oil painting"),
        ]
    )


class TestSingleReference:
    """
    Qwen 2.1 Image takes a tag only when two or more images are attached, so a
    lone reference must not be numbered anywhere in the rendered prompt.
    """

    def test_no_image_number_is_rendered(self, one_reference):
        assert "IMAGE 1" not in one_reference
        assert "IMAGE 2" not in one_reference

    def test_the_reference_is_labelled_and_its_analysis_kept(self, one_reference):
        assert "THE REFERENCE: a tall woman with red hair" in one_reference

    def test_the_guideline_asks_for_natural_wording(self, one_reference):
        assert "as in the reference image" in one_reference

    def test_a_reference_without_analysis_still_reports_its_tags(self):
        rendered = render([asset(tags=["red hair", "tavern"])])

        assert "THE REFERENCE: No analysis available" in rendered
        assert "red hair, tavern" in rendered

    def test_a_reference_without_analysis_or_tags_says_so(self):
        rendered = render([asset()])

        assert "THE REFERENCE: No analysis available - no tags available" in rendered


class TestSeveralReferences:
    def test_each_reference_keeps_its_number(self, two_references):
        assert "IMAGE 1: a tall woman with red hair" in two_references
        assert "IMAGE 2: an oil painting" in two_references

    def test_the_guideline_asks_for_the_image_number(self, two_references):
        assert "Reference by image number" in two_references

    def test_the_guideline_asks_for_the_label_verbatim(self, two_references):
        # the finalizer preset matches capitals, so the label the model writes
        # has to be the one the preset looks for
        assert "verbatim in capitals, exactly as IMAGE 1, IMAGE 2" in two_references

    def test_the_verbatim_instruction_is_absent_for_one_reference(self, one_reference):
        assert "verbatim in capitals" not in one_reference

    def test_the_single_reference_wording_is_absent(self, two_references):
        assert "as in the reference image" not in two_references
        assert "THE REFERENCE" not in two_references


class TestVisualAssetModuleReferenceListing:
    """
    The `Jinja2 Format` node of `agents/visual/generateVisualAsset` lists the
    selected references in the prompt itself. That listing reaches the image
    backend whenever prompt revision is off, so it branches on the count too.
    """

    NODE_ID = "22d2147f-082b-408c-8e6c-dcbcdd2286a4"

    @pytest.fixture
    def template(self):
        module = json.loads(
            (
                pathlib.Path("src/talemate/agents/visual/modules")
                / "generate-visual-asset.json"
            ).read_text(encoding="utf-8")
        )
        return module["nodes"][self.NODE_ID]["properties"]["template"]

    def render(self, template, references):
        return Prompt.from_text(template, vars={"references": references}).render()

    def test_one_reference_is_listed_without_a_number(self, template):
        rendered = self.render(
            template, [{"purpose": "Use this image as character reference for Kaira."}]
        )

        assert rendered.strip() == "Use this image as character reference for Kaira."

    def test_several_references_keep_their_numbers(self, template):
        rendered = self.render(
            template,
            [
                {"purpose": "Character reference for Kaira."},
                {"purpose": "Style reference."},
            ],
        )

        assert "IMAGE 1: Character reference for Kaira." in rendered
        assert "IMAGE 2: Style reference." in rendered

    def test_no_reference_lists_nothing(self, template):
        assert self.render(template, []).strip() == ""
