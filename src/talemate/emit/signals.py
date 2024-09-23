from blinker import signal

SystemMessage = signal("system")
NarratorMessage = signal("narrator")
CharacterMessage = signal("character")
PlayerMessage = signal("player")
DirectorMessage = signal("director")
TimePassageMessage = signal("time")
StatusMessage = signal("status")
ReinforcementMessage = signal("reinforcement")

ClearScreen = signal("clear_screen")

RequestInput = signal("request_input")
ReceiveInput = signal("receive_input")

ClientStatus = signal("client_status")
RequestClientStatus = signal("request_client_status")
AgentStatus = signal("agent_status")
RequestAgentStatus = signal("request_agent_status")
ClientBootstraps = signal("client_bootstraps")
PromptSent = signal("prompt_sent")
MemoryRequest = signal("memory_request")

RemoveMessage = signal("remove_message")

SceneStatus = signal("scene_status")
CommandStatus = signal("command_status")
WorldState = signal("world_state")
ArchivedHistory = signal("archived_history")

AudioQueue = signal("audio_queue")

MessageEdited = signal("message_edited")

ConfigSaved = signal("config_saved")

ImageGenerated = signal("image_generated")
ImageGenerationFailed = signal("image_generation_failed")

AutocompleteSuggestion = signal("autocomplete_suggestion")

SpiceApplied = signal("spice_applied")

handlers = {
    "system": SystemMessage,
    "narrator": NarratorMessage,
    "character": CharacterMessage,
    "player": PlayerMessage,
    "director": DirectorMessage,
    "time": TimePassageMessage,
    "reinforcement": ReinforcementMessage,
    "request_input": RequestInput,
    "receive_input": ReceiveInput,
    "client_status": ClientStatus,
    "request_client_status": RequestClientStatus,
    "agent_status": AgentStatus,
    "request_agent_status": RequestAgentStatus,
    "client_bootstraps": ClientBootstraps,
    "clear_screen": ClearScreen,
    "remove_message": RemoveMessage,
    "scene_status": SceneStatus,
    "command_status": CommandStatus,
    "world_state": WorldState,
    "archived_history": ArchivedHistory,
    "message_edited": MessageEdited,
    "prompt_sent": PromptSent,
    "audio_queue": AudioQueue,
    "config_saved": ConfigSaved,
    "status": StatusMessage,
    "image_generated": ImageGenerated,
    "image_generation_failed": ImageGenerationFailed,
    "autocomplete_suggestion": AutocompleteSuggestion,
    "spice_applied": SpiceApplied,
    "memory_request": MemoryRequest,
}
