__all__ = [
    "configure",
    "set_max_tokens",
    "set_preset",
    "preset_for_kind",
    "max_tokens_for_kind",
    "PRESET_TALEMATE_CONVERSATION",
    "PRESET_TALEMATE_CREATOR",
    "PRESET_LLAMA_PRECISE",
    "PRESET_DIVINE_INTELLECT",
    "PRESET_SIMPLE_1",
]

# TODO: refactor abstraction and make configurable

import token


PRESENCE_PENALTY_BASE = 0.2
FREQUENCY_PENALTY_BASE = 0.2
MIN_P_BASE = 0.1  # range of 0.05-0.15 is reasonable
TEMPERATURE_LAST = True

PRESET_TALEMATE_CONVERSATION = {
    "temperature": 0.65,
    "top_p": 0.47,
    "top_k": 42,
    "presence_penalty": PRESENCE_PENALTY_BASE,
    "frequency_penalty": FREQUENCY_PENALTY_BASE,
    "min_p": MIN_P_BASE,
    "temperature_last": TEMPERATURE_LAST,
    "repetition_penalty": 1.18,
    "repetition_penalty_range": 2048,
}

# Fixed value template for experimentation
PRESET_TALEMATE_CONVERSATION_FIXED = {
    "temperature": 1,
    "top_p": 1,
    "top_k": 0,
    "presence_penalty": PRESENCE_PENALTY_BASE,
    "frequency_penalty": FREQUENCY_PENALTY_BASE,
    "min_p": MIN_P_BASE,
    "temperature_last": TEMPERATURE_LAST,
    "repetition_penalty": 1.1,
    "repetition_penalty_range": 2048,
}

PRESET_TALEMATE_CREATOR = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 20,
    "presence_penalty": PRESENCE_PENALTY_BASE,
    "frequency_penalty": FREQUENCY_PENALTY_BASE,
    "min_p": MIN_P_BASE,
    "temperature_last": TEMPERATURE_LAST,
    "repetition_penalty": 1.15,
    "repetition_penalty_range": 512,
}

PRESET_LLAMA_PRECISE = {
    "temperature": 0.7,
    "top_p": 0.1,
    "top_k": 40,
    "presence_penalty": PRESENCE_PENALTY_BASE,
    "frequency_penalty": FREQUENCY_PENALTY_BASE,
    "min_p": MIN_P_BASE,
    "temperature_last": TEMPERATURE_LAST,
    "repetition_penalty": 1.18,
}

PRESET_DETERMINISTIC = {
    "temperature": 0.1,
    "top_p": 1,
    "top_k": 0,
    "repetition_penalty": 1.0,
}

PRESET_DIVINE_INTELLECT = {
    "temperature": 1.31,
    "top_p": 0.14,
    "top_k": 49,
    "presence_penalty": PRESENCE_PENALTY_BASE,
    "frequency_penalty": FREQUENCY_PENALTY_BASE,
    "min_p": MIN_P_BASE,
    "temperature_last": TEMPERATURE_LAST,
    "repetition_penalty_range": 1024,
    "repetition_penalty": 1.17,
}

PRESET_SIMPLE_1 = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 20,
    "presence_penalty": PRESENCE_PENALTY_BASE,
    "frequency_penalty": FREQUENCY_PENALTY_BASE,
    "min_p": MIN_P_BASE,
    "temperature_last": TEMPERATURE_LAST,
    "repetition_penalty": 1.15,
}

PRESET_ANALYTICAL = {
    "temperature": 0.1,
    "top_p": 0.9,
    "top_k": 20,
}


def configure(config: dict, kind: str, total_budget: int, client=None):
    """
    Sets the config based on the kind of text to generate.
    """
    set_preset(config, kind, client)
    set_max_tokens(config, kind, total_budget)
    return config


def set_max_tokens(config: dict, kind: str, total_budget: int):
    """
    Sets the max_tokens in the config based on the kind of text to generate.
    """
    config["max_tokens"] = max_tokens_for_kind(kind, total_budget)
    return config


def set_preset(config: dict, kind: str, client=None):
    """
    Sets the preset in the config based on the kind of text to generate.
    """
    config.update(preset_for_kind(kind, client))


PRESET_SUBSTRING_MAPPINGS = {
    "deterministic": PRESET_DETERMINISTIC,
    "creative": PRESET_DIVINE_INTELLECT,
    "simple": PRESET_SIMPLE_1,
    "analytical": PRESET_ANALYTICAL
}

PRESET_MAPPING = {
    "conversation": PRESET_TALEMATE_CONVERSATION,
    "conversation_old": PRESET_TALEMATE_CONVERSATION,
    "conversation_long": PRESET_TALEMATE_CONVERSATION,
    "conversation_select_talking_actor": PRESET_TALEMATE_CONVERSATION,
    "summarize": PRESET_LLAMA_PRECISE,
    "analyze": PRESET_SIMPLE_1,
    "analyze_creative": PRESET_DIVINE_INTELLECT,
    "analyze_long": PRESET_SIMPLE_1,
    "analyze_freeform": PRESET_LLAMA_PRECISE,
    "analyze_freeform_short": PRESET_LLAMA_PRECISE,
    "narrate": PRESET_LLAMA_PRECISE,
    "story": PRESET_DIVINE_INTELLECT,
    "create": PRESET_TALEMATE_CREATOR,
    "create_concise": PRESET_TALEMATE_CREATOR,
    "create_precise": PRESET_LLAMA_PRECISE,
    "director": PRESET_SIMPLE_1,
    "director_short": PRESET_SIMPLE_1,
    "director_yesno": PRESET_SIMPLE_1,
    "edit_dialogue": PRESET_DIVINE_INTELLECT,
    "edit_add_detail": PRESET_DIVINE_INTELLECT,
    "edit_fix_exposition": PRESET_DETERMINISTIC,
    "edit_fix_continuity": PRESET_DETERMINISTIC,
    "visualize": PRESET_SIMPLE_1,
}


def preset_for_kind(kind: str) -> dict:
    # Check the substrings first(based on order of the original elifs)
    for substring, value in PRESET_SUBSTRING_MAPPINGS.items():
        if substring in kind:
            return value
    # Default to PRESET_SIMPLE_1 if kind is not found
    return PRESET_MAPPING.get(kind, PRESET_SIMPLE_1)


TOKEN_MAPPING = {
    "conversation": 75,
    "conversation_old": 75,
    "conversation_long": 300,
    "conversation_select_talking_actor": 30,
    "summarize": 500,
    "analyze": 500,
    "analyze_creative": 1024,
    "analyze_long": 2048,
    "analyze_freeform": 500,
    "analyze_freeform_medium": 192,
    "analyze_freeform_medium_short": 128,
    "analyze_freeform_short": 10,
    "narrate": 500,
    "story": 300,
    "create": lambda total_budget: min(1024, int(total_budget * 0.35)),
    "create_concise": lambda total_budget: min(400, int(total_budget * 0.25)),
    "create_precise": lambda total_budget: min(400, int(total_budget * 0.25)),
    "create_short": 25,
    "director": lambda total_budget: min(192, int(total_budget * 0.25)),
    "director_short": 25,
    "director_yesno": 2,
    "edit_dialogue": 100,
    "edit_add_detail": 200,
    "edit_fix_exposition": 1024,
    "edit_fix_continuity": 512,
    "visualize": 150,
}

TOKEN_SUBSTRING_MAPPINGS = {
    "extensive": 2048,
    "long": 1024,
    "medium2": 512,
    "medium": 192,
    "short2": 128,
    "short": 75,
    "tiny2": 25,
    "tiny": 10,
    "yesno": 2,
}


def max_tokens_for_kind(kind: str, total_budget: int) -> int:
    token_value = TOKEN_MAPPING.get(kind)
    if callable(token_value):
        return token_value(total_budget)
    # If no exact match, check for substrings (order of original elifs)
    for substring, value in TOKEN_SUBSTRING_MAPPINGS.items():
        if substring in kind:
            return value
    if token_value is not None:
        return token_value
    return 150  # Default value if none of the kinds match