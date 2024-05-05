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

PRESET_TALEMATE_CONVERSATION = {
    "temperature": 0.65,
    "top_p": 0.47,
    "top_k": 42,
    "repetition_penalty": 1.18,
    "repetition_penalty_range": 2048,
}

PRESET_TALEMATE_CREATOR = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 20,
    "repetition_penalty": 1.15,
    "repetition_penalty_range": 512,
}

PRESET_LLAMA_PRECISE = {
    "temperature": 0.7,
    "top_p": 0.1,
    "top_k": 40,
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
    "repetition_penalty_range": 1024,
    "repetition_penalty": 1.17,
}

PRESET_SIMPLE_1 = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 20,
    "repetition_penalty": 1.15,
}

PRESET_ANALYTICAL = {
    "temperature": 0.1,
    "top_p": 0.9,
    "top_k": 20,
}


def configure(config: dict, kind: str, total_budget: int):
    """
    Sets the config based on the kind of text to generate.
    """
    set_preset(config, kind)
    set_max_tokens(config, kind, total_budget)
    return config


def set_max_tokens(config: dict, kind: str, total_budget: int):
    """
    Sets the max_tokens in the config based on the kind of text to generate.
    """
    config["max_tokens"] = max_tokens_for_kind(kind, total_budget)
    return config


def set_preset(config: dict, kind: str):
    """
    Sets the preset in the config based on the kind of text to generate.
    """
    config.update(preset_for_kind(kind))


def preset_for_kind(kind: str):

    # tag based
    if "deterministic" in kind:
        return PRESET_DETERMINISTIC
    elif "creative" in kind:
        return PRESET_DIVINE_INTELLECT
    elif "simple" in kind:
        return PRESET_SIMPLE_1
    elif "analytical" in kind:
        return PRESET_ANALYTICAL
    elif kind == "conversation":
        return PRESET_TALEMATE_CONVERSATION
    elif kind == "conversation_old":
        return PRESET_TALEMATE_CONVERSATION  # Assuming old conversation uses the same preset
    elif kind == "conversation_long":
        return PRESET_TALEMATE_CONVERSATION  # Assuming long conversation uses the same preset
    elif kind == "conversation_select_talking_actor":
        return PRESET_TALEMATE_CONVERSATION  # Assuming select talking actor uses the same preset
    elif kind == "summarize":
        return PRESET_LLAMA_PRECISE
    elif kind == "analyze":
        return PRESET_SIMPLE_1
    elif kind == "analyze_creative":
        return PRESET_DIVINE_INTELLECT
    elif kind == "analyze_long":
        return PRESET_SIMPLE_1  # Assuming long analysis uses the same preset as simple
    elif kind == "analyze_freeform":
        return PRESET_LLAMA_PRECISE
    elif kind == "analyze_freeform_short":
        return PRESET_LLAMA_PRECISE  # Assuming short freeform analysis uses the same preset as precise
    elif kind == "narrate":
        return PRESET_LLAMA_PRECISE
    elif kind == "story":
        return PRESET_DIVINE_INTELLECT
    elif kind == "create":
        return PRESET_TALEMATE_CREATOR
    elif kind == "create_concise":
        return PRESET_TALEMATE_CREATOR  # Assuming concise creation uses the same preset as creator
    elif kind == "create_precise":
        return PRESET_LLAMA_PRECISE
    elif kind == "director":
        return PRESET_SIMPLE_1
    elif kind == "director_short":
        return (
            PRESET_SIMPLE_1  # Assuming short direction uses the same preset as simple
        )
    elif kind == "director_yesno":
        return (
            PRESET_SIMPLE_1  # Assuming yes/no direction uses the same preset as simple
        )
    elif kind == "edit_dialogue":
        return PRESET_DIVINE_INTELLECT
    elif kind == "edit_add_detail":
        return PRESET_DIVINE_INTELLECT  # Assuming adding detail uses the same preset as divine intellect
    elif kind == "edit_fix_exposition":
        return PRESET_DETERMINISTIC  # Assuming fixing exposition uses the same preset as divine intellect
    elif kind == "edit_fix_continuity":
        return PRESET_DETERMINISTIC
    elif kind == "visualize":
        return PRESET_SIMPLE_1

    else:
        return PRESET_SIMPLE_1  # Default preset if none of the kinds match


def max_tokens_for_kind(kind: str, total_budget: int):
    if kind == "conversation":
        return 75
    elif kind == "conversation_old":
        return 75
    elif kind == "conversation_long":
        return 300
    elif kind == "conversation_select_talking_actor":
        return 30
    elif kind == "summarize":
        return 500
    elif kind == "analyze":
        return 500
    elif kind == "analyze_creative":
        return 1024
    elif kind == "analyze_long":
        return 2048
    elif kind == "analyze_freeform":
        return 500
    elif kind == "analyze_freeform_medium":
        return 192
    elif kind == "analyze_freeform_medium_short":
        return 128
    elif kind == "analyze_freeform_short":
        return 10
    elif kind == "narrate":
        return 500
    elif kind == "story":
        return 300
    elif kind == "create":
        return min(1024, int(total_budget * 0.35))
    elif kind == "create_concise":
        return min(400, int(total_budget * 0.25))
    elif kind == "create_precise":
        return min(400, int(total_budget * 0.25))
    elif kind == "create_short":
        return 25
    elif kind == "director":
        return min(192, int(total_budget * 0.25))
    elif kind == "director_short":
        return 25
    elif kind == "director_yesno":
        return 2
    elif kind == "edit_dialogue":
        return 100
    elif kind == "edit_add_detail":
        return 200
    elif kind == "edit_fix_exposition":
        return 1024
    elif kind == "edit_fix_continuity":
        return 512
    elif kind == "visualize":
        return 150
    # tag based
    elif "extensive" in kind:
        return 2048
    elif "long" in kind:
        return 1024
    elif "medium2" in kind:
        return 512
    elif "medium" in kind:
        return 192
    elif "short2" in kind:
        return 128
    elif "short" in kind:
        return 75
    elif "tiny2" in kind:
        return 25
    elif "tiny" in kind:
        return 10
    elif "yesno" in kind:
        return 2
    else:
        return 150  # Default value if none of the kinds match
