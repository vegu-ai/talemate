import structlog
import yaml
from talemate.path import CONFIG_FILE
import talemate.emit.async_signals as async_signals
from talemate.agents.registry import get_agent_class
from talemate.client.registry import get_client_class

from .schema import Config

log = structlog.get_logger("talemate.config")

CONFIG = None

async_signals.register(
    "config.saved",
    "config.saved.after",
    "config.loaded",
)


def _load_config() -> Config:
    print("loading config", str(CONFIG_FILE))
    with open(CONFIG_FILE, "r") as file:
        yaml_data = yaml.safe_load(file)
        return Config.model_validate(yaml_data)


def get_config() -> Config:
    global CONFIG
    if CONFIG is None:
        CONFIG = _load_config()
    return CONFIG


async def update_config(other_config: Config | dict):
    if isinstance(other_config, dict):
        keys = list(other_config.keys())
        other_config = Config.model_validate(other_config)
    else:
        keys = None

    config: Config = get_config()

    # if keys is None, do full update
    if keys is None:
        for field in Config.model_fields:
            setattr(config, field.name, getattr(other_config, field.name))
    else:
        for key in keys:
            setattr(config, key, getattr(other_config, key))

    await config.set_dirty()


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


def cleanup() -> Config:
    log.info("cleaning up config")

    config = get_config()

    cleanup_removed_clients(config)
    cleanup_removed_agents(config)

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
