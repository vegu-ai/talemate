import os
from typing import Literal

import structlog
import yaml
from talemate.path import CONFIG_FILE
import talemate.emit.async_signals as async_signals
from talemate.agents.registry import get_agent_class
from talemate.client.registry import get_client_class
from talemate.files import scene_file_hidden
from talemate.util.encryption import decrypt_sensitive_values, encrypt_sensitive_values

from .schema import Config

log = structlog.get_logger("talemate.config")

CONFIG = None

async_signals.register(
    "config.saved",
    "config.saved.after",
    "config.loaded",
)

ApplySectionKey = Literal["clients", "agents", "decision_model"]

# config sections whose apply failed and that the next config save has to
# apply again even when they diff as unchanged - the config is stored before it
# is applied, so a failed apply leaves the stored config ahead of the running
# instance and every later diff against it reads "nothing changed"
PENDING_APPLY: set[ApplySectionKey] = set()


def mark_apply_pending(*sections: ApplySectionKey) -> None:
    PENDING_APPLY.update(sections)


def _load_config() -> Config:
    log.debug("loading config", file_path=CONFIG_FILE)
    try:
        file = open(CONFIG_FILE, "r")
    except FileNotFoundError:
        log.info("config file not found, starting with defaults", file_path=CONFIG_FILE)
        return Config()
    with file:
        yaml_data = yaml.safe_load(file)
        if yaml_data is None:
            yaml_data = {}
        decrypt_sensitive_values(yaml_data)
        return Config.model_validate(yaml_data)


def get_config() -> Config:
    global CONFIG
    if CONFIG is None:
        CONFIG = _load_config()
    return CONFIG


async def update_config(other_config: dict, signal: bool = True):
    """Apply a partial config update from a dict.

    Each top-level key in ``other_config`` replaces the corresponding field
    on the active ``Config`` (validated through pydantic first).

    ``signal=False`` marks the config dirty without firing ``config.changed``.
    Receivers of that signal broadcast the config to connected frontends, so a
    caller that still has to APPLY the update (instantiate clients, reconfigure
    agents) uses it to hold the broadcast back until the running instance
    matches what it ships, then fires ``set_dirty()`` itself.
    """
    keys = list(other_config.keys())
    validated = Config.model_validate(other_config)

    config: Config = get_config()
    for key in keys:
        setattr(config, key, getattr(validated, key))

    if not signal:
        # still dirty: commit_config() is what writes it to disk
        config.dirty = True
        return

    await config.set_dirty()


def _strip_unified_api_key_configs(config: dict):
    """
    Remove unified_api_key entries from agent action configs before saving.

    These are static reference pointers (e.g., 'openai.api_key') defined in
    agent code — they never change and should not be persisted.
    """
    from talemate.instance import AGENTS

    for agent_name, agent_data in config.get("agents", {}).items():
        agent = AGENTS.get(agent_name)
        if not agent or not getattr(agent, "actions", None):
            continue

        actions = agent_data.get("actions", {})
        for action_key, action_data in actions.items():
            runtime_action = agent.actions.get(action_key)
            if not runtime_action or not runtime_action.config:
                continue

            saved_config = action_data.get("config", {})
            for config_key in list(saved_config.keys()):
                runtime_cfg = runtime_action.config.get(config_key)
                if runtime_cfg and runtime_cfg.type == "unified_api_key":
                    del saved_config[config_key]


def save_config():
    """
    Save the config file to the given path.
    """

    log.debug("Saving config", file_path=CONFIG_FILE)

    config = get_config().model_dump(exclude_none=True)

    # we dont want to persist the following, so we drop them:
    # - presets.inference_defaults
    # - presets.embeddings_defaults

    if "inference_defaults" in config["presets"]:
        config["presets"].pop("inference_defaults")

    if "embeddings_defaults" in config["presets"]:
        config["presets"].pop("embeddings_defaults")

    # for normal presets we only want to persist if they have changed
    for preset_name, preset in list(config["presets"]["inference"].items()):
        if not preset.get("changed"):
            config["presets"]["inference"].pop(preset_name)

    # in inference groups also only keep if changed
    for _, group in list(config["presets"]["inference_groups"].items()):
        for preset_name, preset in list(group["presets"].items()):
            if not preset.get("changed"):
                group["presets"].pop(preset_name)

    # if presets is empty, remove it
    if not config["presets"]["inference"]:
        config["presets"].pop("inference")

    # if system_prompts is empty, remove it
    if not config["system_prompts"]:
        config.pop("system_prompts")

    # set any client preset_group to "" if it references an
    # entry that no longer exists in inference_groups
    for client in config["clients"].values():
        if not client.get("preset_group"):
            continue

        if client["preset_group"] not in config["presets"].get("inference_groups", {}):
            log.warning(
                f"Client {client['name']} references non-existent preset group {client['preset_group']}, setting to default"
            )
            client["preset_group"] = ""

    # the inference param panel is pinned to one client by name, which a
    # client removal or rename leaves pointing at nothing. Cleared on the live
    # model too: every status broadcast is built from that, so a name only
    # dropped from the file would keep reaching the frontend until a restart
    panel = config["presets"]["inference_param_panel"]
    if panel.get("client") and panel["client"] not in config["clients"]:
        log.warning(
            f"Inference param panel references non-existent client {panel['client']}, clearing it"
        )
        panel["client"] = None
        get_config().presets.inference_param_panel.client = None

    _strip_unified_api_key_configs(config)

    encrypt_sensitive_values(config)

    with open(CONFIG_FILE, "w") as file:
        yaml.dump(config, file)


def cleanup_removed_clients(config: Config):
    """
    Will remove any clients that are no longer present
    """

    if not config:
        return

    for client_in_config in list(config.clients.keys()):
        client_config = config.clients[client_in_config]
        if not get_client_class(client_config.type):
            log.info("removing client from config", client=client_in_config)
            del config.clients[client_in_config]


def cleanup_removed_agents(config: Config):
    """
    Will remove any agents that are no longer present
    """

    if not config:
        return

    for agent_in_config in list(config.agents.keys()):
        if not get_agent_class(agent_in_config):
            log.info("removing agent from config", agent=agent_in_config)
            del config.agents[agent_in_config]


def cleanup_removed_recent_scenes(config: Config):
    """
    Will remove any recent scenes that are no longer present or that are
    hidden from the scene browser
    """

    if not config:
        return

    for recent_scene in list(config.recent_scenes.scenes):
        if not os.path.exists(recent_scene.path):
            log.debug("recent scene path no longer exists", scene=recent_scene.path)
            config.recent_scenes.scenes.remove(recent_scene)
        elif scene_file_hidden(recent_scene.path):
            log.debug("recent scene is hidden", scene=recent_scene.path)
            config.recent_scenes.scenes.remove(recent_scene)


def cleanup_instructor_embeddings(config: Config):
    """
    Will reset memory agent embeddings to default if they reference instructor embeddings.
    Also removes any instructor embedding presets.
    """

    if not config:
        return

    # Check memory agent configuration
    memory_agent = config.agents.get("memory")
    if memory_agent and memory_agent.actions:
        _config_action = memory_agent.actions.get("_config")
        if _config_action and _config_action.config:
            embeddings_config = _config_action.config.get("embeddings")
            if embeddings_config and embeddings_config.value:
                embeddings_preset_key = embeddings_config.value
                embeddings_preset = config.presets.embeddings.get(embeddings_preset_key)

                # Check if the preset is an instructor embedding
                if embeddings_preset and embeddings_preset.embeddings == "instructor":
                    log.info(
                        "resetting memory agent embeddings to default",
                        old_preset=embeddings_preset_key,
                    )
                    embeddings_config.value = "default"
                    # Mark config as dirty so it gets saved
                    config.dirty = True

    # Remove any instructor embedding presets
    for preset_key, preset in list(config.presets.embeddings.items()):
        if preset.embeddings == "instructor":
            log.info("removing instructor embedding preset", preset=preset_key)
            del config.presets.embeddings[preset_key]
            # Mark config as dirty so it gets saved
            config.dirty = True


def restore_missing_embedding_presets(config: Config):
    """
    Adds shipped embedding presets that a saved config predates.

    `save_config` persists `presets.embeddings` in full and the load replaces
    the dict wholesale, so a config written before a preset shipped would
    never see it.
    """

    if not config:
        return

    for preset_key, preset in config.presets.embeddings_defaults.items():
        if preset_key in config.presets.embeddings:
            continue

        log.info("restoring shipped embedding preset", preset=preset_key)
        config.presets.embeddings[preset_key] = preset.model_copy(deep=True)


def cleanup() -> Config:
    log.info("cleaning up config")

    config = get_config()

    cleanup_removed_clients(config)
    cleanup_removed_agents(config)
    cleanup_removed_recent_scenes(config)
    cleanup_instructor_embeddings(config)
    restore_missing_embedding_presets(config)

    save_config()

    return config


async def commit_config():
    """
    Will commit the config to the file
    """

    config = get_config()
    if not config.dirty:
        return

    save_config()
    config.dirty = False

    await async_signals.get("config.saved").send(config)
