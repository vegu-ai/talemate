from blinker import signal

SystemMessage = signal("system")
NarratorMessage = signal("narrator")
CharacterMessage = signal("character")
PlayerMessage = signal("player")
DirectorMessage = signal("director")
TimePassageMessage = signal("time")
StatusMessage = signal("status")
AgentMessage = signal("agent")
ReinforcementMessage = signal("reinforcement")
PlayerChoiceMessage = signal("player_choice")
ContextInvestigationMessage = signal("context_investigation")
UxMessage = signal("ux")

ClearScreen = signal("clear_screen")

RequestInput = signal("request_input")
ReceiveInput = signal("receive_input")

ClientStatus = signal("client_status")
RateLimited = signal("rate_limited")
RateLimitReset = signal("rate_limit_reset")
RequestClientStatus = signal("request_client_status")
AgentStatus = signal("agent_status")
RequestAgentStatus = signal("request_agent_status")
PromptSent = signal("prompt_sent")
MemoryRequest = signal("memory_request")

RemoveMessage = signal("remove_message")

SceneStatus = signal("scene_status")
SceneIntent = signal("scene_intent")
CommandStatus = signal("command_status")
WorldState = signal("world_state")
ArchivedHistory = signal("archived_history")

AudioQueue = signal("audio_queue")

MessageEdited = signal("message_edited")
MessageAssetUpdate = signal("message_asset_update")

ImageGenerated = signal("image_generated")
ImageGenerationFailed = signal("image_generation_failed")
ImageAnalyzed = signal("image_analyzed")
ImageAnalysisFailed = signal("image_analysis_failed")

AutocompleteSuggestion = signal("autocomplete_suggestion")

SpiceApplied = signal("spice_applied")

WorldSateManager = signal("world_state_manager")

TalemateStarted = signal("talemate_started")

RequestActionConfirmation = signal("request_action_confirmation")

SceneCoverImageSet = signal("scene_asset_scene_cover_image")
CharacterCoverImageSet = signal("scene_asset_character_cover_image")
CharacterAvatarSet = signal("scene_asset_character_avatar")
CharacterCurrentAvatarSet = signal("scene_asset_character_current_avatar")

handlers = {
    "system": SystemMessage,
    "narrator": NarratorMessage,
    "character": CharacterMessage,
    "player": PlayerMessage,
    "director": DirectorMessage,
    "time": TimePassageMessage,
    "context_investigation": ContextInvestigationMessage,
    "reinforcement": ReinforcementMessage,
    "request_input": RequestInput,
    "receive_input": ReceiveInput,
    "client_status": ClientStatus,
    "rate_limited": RateLimited,
    "rate_limit_reset": RateLimitReset,
    "request_client_status": RequestClientStatus,
    "agent_status": AgentStatus,
    "request_agent_status": RequestAgentStatus,
    "clear_screen": ClearScreen,
    "remove_message": RemoveMessage,
    "agent_message": AgentMessage,
    "scene_status": SceneStatus,
    "scene_intent": SceneIntent,
    "command_status": CommandStatus,
    "world_state": WorldState,
    "archived_history": ArchivedHistory,
    "message_edited": MessageEdited,
    "message_asset_update": MessageAssetUpdate,
    "prompt_sent": PromptSent,
    "audio_queue": AudioQueue,
    "status": StatusMessage,
    "image_generated": ImageGenerated,
    "image_generation_failed": ImageGenerationFailed,
    "image_analyzed": ImageAnalyzed,
    "image_analysis_failed": ImageAnalysisFailed,
    "autocomplete_suggestion": AutocompleteSuggestion,
    "spice_applied": SpiceApplied,
    "memory_request": MemoryRequest,
    "player_choice": PlayerChoiceMessage,
    "ux": UxMessage,
    "world_state_manager": WorldSateManager,
    "talemate_started": TalemateStarted,
    "request_action_confirmation": RequestActionConfirmation,
    "scene_asset_scene_cover_image": SceneCoverImageSet,
    "scene_asset_character_cover_image": CharacterCoverImageSet,
    "scene_asset_character_avatar": CharacterAvatarSet,
    "scene_asset_character_current_avatar": CharacterCurrentAvatarSet,
}
