import copy
import random


def jiggle_randomness(prompt_config: dict, offset: float = 0.3) -> dict:
    """
    adjusts temperature and repetition_penalty
    by random values using the base value as a center
    """

    temp = prompt_config["temperature"]
    rep_pen = prompt_config["repetition_penalty"]

    copied_config = copy.deepcopy(prompt_config)

    min_offset = offset * 0.3

    copied_config["temperature"] = random.uniform(temp + min_offset, temp + offset)
    copied_config["repetition_penalty"] = random.uniform(
        rep_pen + min_offset * 0.3, rep_pen + offset * 0.3
    )

    return copied_config


def jiggle_enabled_for(kind: str):
    if kind in ["conversation", "story"]:
        return True

    if kind.startswith("narrate"):
        return True

    return False
