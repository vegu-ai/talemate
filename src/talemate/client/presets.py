from typing import TYPE_CHECKING
from talemate.config import load_config, InferencePresets
from talemate.emit.signals import handlers
from talemate.client.context import set_client_context_attribute
import structlog

if TYPE_CHECKING:
    from talemate.client.base import ClientBase
    
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

log = structlog.get_logger("talemate.client.presets")

config = load_config(as_model=True)

# Load the config
CONFIG = {
    "inference": config.presets.inference,
}


# Sync the config when it is saved
def sync_config(event):
    CONFIG["inference"] = InferencePresets(
        **event.data.get("presets", {}).get("inference", {})
    )
    
handlers["config_saved"].connect(sync_config)


def get_inference_parameters(preset_name: str) -> dict:
    """
    Returns the inference parameters for the given preset name.
    """
    presets = CONFIG["inference"].model_dump()
    if preset_name in presets:
        return presets[preset_name]
    
    raise ValueError(f"Preset name {preset_name} not found in presets.inference")


def configure(parameters: dict, kind: str, total_budget: int, client: "ClientBase"):
    """
    Sets the config based on the kind of text to generate.
    """
    set_preset(parameters, kind, client)
    set_max_tokens(parameters, kind, total_budget)
    return parameters


def set_max_tokens(parameters: dict, kind: str, total_budget: int):
    """
    Sets the max_tokens in the config based on the kind of text to generate.
    """
    parameters["max_tokens"] = max_tokens_for_kind(kind, total_budget)
    return parameters


def set_preset(parameters: dict, kind: str, client: "ClientBase"):
    """
    Sets the preset in the config based on the kind of text to generate.
    """
    parameters.update(preset_for_kind(kind, client))


# TODO: can this just be checking all keys in inference.presets.inference?
PRESET_SUBSTRING_MAPPINGS = {
    "deterministic": "deterministic",
    "creative": "creative",
    "analytical": "analytical",
    "analyze": "analytical",
}

PRESET_MAPPING = {
    "conversation": "conversation",
    "conversation_select_talking_actor": "analytical",
    "summarize": "summarization",
    "analyze": "analytical",
    "analyze_long": "analytical",
    "analyze_freeform": "analytical",
    "analyze_freeform_short": "analytical",
    "narrate": "creative",
    "create": "creative_instruction",
    "create_short": "creative_instruction",
    "create_concise": "creative_instruction",
    "director": "scene_direction",
    "edit_add_detail": "creative",
    "edit_fix_exposition": "deterministic",
    "edit_fix_continuity": "deterministic",
    "visualize": "creative_instruction",
}


def preset_for_kind(kind: str, client: "ClientBase") -> dict:
    # Check the substrings first(based on order of the original elifs)
    
    preset_name = None
    
    preset_name = PRESET_MAPPING.get(kind)
    
    if not preset_name:
        for substring, value in PRESET_SUBSTRING_MAPPINGS.items():
            if substring in kind:
                preset_name = value
        
    if not preset_name:
        log.warning(f"No preset found for kind {kind}, defaulting to 'scene_direction'", presets=CONFIG["inference"])
        preset_name = "scene_direction"
    
    set_client_context_attribute("inference_preset", preset_name)
    
    return get_inference_parameters(preset_name)


TOKEN_MAPPING = {
    "conversation": 75,
    "conversation_select_talking_actor": 30,
    "summarize": 500,
    "analyze": 500,
    "analyze_long": 2048,
    "analyze_freeform": 500,
    "analyze_freeform_medium": 192,
    "analyze_freeform_medium_short": 128,
    "analyze_freeform_short": 10,
    "narrate": 500,
    "story": 300,
    "create": lambda total_budget: min(1024, int(total_budget * 0.35)),
    "create_concise": lambda total_budget: min(400, int(total_budget * 0.25)),
    "create_short": 25,
    "director": lambda total_budget: min(192, int(total_budget * 0.25)),
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