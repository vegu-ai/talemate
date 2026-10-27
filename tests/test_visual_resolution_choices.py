import pytest

from talemate.agents.visual.backends.utils import (
    RESOLUTION_PRESETS,
    get_resolution_choices,
)

FORMATS = ("square", "portrait", "landscape")

MEGAPIXEL_PRESETS = ("0.4 MP", "0.8 MP", "1 MP", "1.4 MP", "2 MP")

MODEL_PRESETS = ("SD 1.5", "SDXL", "Qwen Image", "Z-Image Turbo")


def labels(format_type: str) -> list[str]:
    return [choice["label"] for choice in get_resolution_choices(format_type)]


@pytest.mark.parametrize("format_type", FORMATS)
def test_every_format_offers_model_then_megapixel_presets(format_type):
    expected = list(MODEL_PRESETS) + list(MEGAPIXEL_PRESETS)
    prefixes = [label.split(" (")[0] for label in labels(format_type)]
    assert prefixes == expected


@pytest.mark.parametrize("format_type", FORMATS)
def test_labels_state_the_resolution(format_type):
    for choice in get_resolution_choices(format_type):
        width, height = choice["value"]
        assert choice["label"].endswith(f" ({width}x{height})")


@pytest.mark.parametrize("format_type", FORMATS)
def test_every_side_is_a_multiple_of_16(format_type):
    for choice in get_resolution_choices(format_type):
        width, height = choice["value"]
        assert width % 16 == 0, choice["label"]
        assert height % 16 == 0, choice["label"]


@pytest.mark.parametrize("label", MEGAPIXEL_PRESETS)
@pytest.mark.parametrize("format_type", FORMATS)
def test_megapixel_sides_are_multiples_of_32(format_type, label):
    width, height = RESOLUTION_PRESETS[label][format_type]
    assert width % 32 == 0, (label, format_type)
    assert height % 32 == 0, (label, format_type)


@pytest.mark.parametrize("label", MEGAPIXEL_PRESETS)
@pytest.mark.parametrize("format_type", FORMATS)
def test_megapixel_presets_stay_within_ten_percent_of_their_budget(format_type, label):
    budget = float(label.removesuffix(" MP")) * 1_000_000
    resolution = RESOLUTION_PRESETS[label][format_type]
    width, height = resolution
    assert abs(width * height - budget) / budget < 0.1, (label, format_type)


@pytest.mark.parametrize("label", MEGAPIXEL_PRESETS + MODEL_PRESETS)
def test_landscape_is_the_transposed_portrait(label):
    resolutions = RESOLUTION_PRESETS[label]
    assert resolutions["landscape"] == list(reversed(resolutions["portrait"]))


@pytest.mark.parametrize("label", MEGAPIXEL_PRESETS + MODEL_PRESETS)
def test_square_presets_are_square(label):
    width, height = RESOLUTION_PRESETS[label]["square"]
    assert width == height
