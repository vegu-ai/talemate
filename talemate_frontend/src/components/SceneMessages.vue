<template>
    <RequestInput
    ref="requestForkName"
    title="Save Forked Scene As"
    :instructions="forkInstructions"
    @continue="(name, params) => { forkScene(params.message_id, name) }" /> 

    <RequestInput
    ref="requestRegenerateInstructions"
    title="Image Editing Instructions"
    instructions="Provide instructions for editing this image."
    @continue="(instructions, params) => { handleRegenerateAssetWithInstructions(instructions, params) }" />

    <!-- Shared Asset Menu -->
    <v-menu
        v-model="assetMenu.show"
        :style="assetMenuStyle"
        :location="assetMenu.location"
        :target="assetMenu.target"
        min-width="500"
        max-width="500"
    >
        <v-list density="compact">
            <v-list-item
                prepend-icon="mdi-image-search"
                @click="handleViewImage"
            >
                <v-list-item-title>View Image</v-list-item-title>
                <v-list-item-subtitle>{{ primaryModifierLabel }}+click</v-list-item-subtitle>
            </v-list-item>
            <v-divider></v-divider>
            <v-list-item
                prepend-icon="mdi-image-multiple-outline"
                @click="handleOpenInVisualLibrary"
            >
                <v-list-item-title>Open in Visual Library</v-list-item-title>
            </v-list-item>
            <v-divider v-if="assetSupportsRegeneration"></v-divider>
            <v-list-item
                v-if="assetSupportsRegeneration"
                :disabled="!visualAgentReady"
                prepend-icon="mdi-image-refresh"
                @click="handleRegenerateIllustration"
            >
                <v-list-item-title>Regenerate Illustration</v-list-item-title>
                <v-list-item-subtitle v-if="visualAgentReady">Shift+click</v-list-item-subtitle>
                <v-list-item-subtitle v-else>Visual agent not ready</v-list-item-subtitle>
            </v-list-item>
            <v-list-item
                v-if="assetSupportsRegeneration"
                :disabled="!visualAgentReady"
                prepend-icon="mdi-image-refresh-outline"
                @click="handleRegenerateAndDeleteIllustration"
            >
                <v-list-item-title>Regenerate and Delete</v-list-item-title>
                <v-list-item-subtitle v-if="visualAgentReady">Alt+click</v-list-item-subtitle>
                <v-list-item-subtitle v-else>Visual agent not ready</v-list-item-subtitle>
            </v-list-item>
            <v-list-item
                v-if="assetSupportsRegeneration"
                :disabled="!visualAgentReady"
                prepend-icon="mdi-image-edit"
                @click="handleOpenRegenerateAssetDialog"
            >
                <v-list-item-title>Edit Illustration</v-list-item-title>
                <v-list-item-subtitle v-if="!visualAgentReady">Visual agent not ready</v-list-item-subtitle>
            </v-list-item>
            <v-list-item
                v-if="assetSupportsRegeneration"
                :disabled="!visualAgentReady"
                prepend-icon="mdi-image-edit-outline"
                @click="handleOpenRegenerateAndDeleteAssetDialog"
            >
                <v-list-item-title>Edit and Delete</v-list-item-title>
                <v-list-item-subtitle v-if="!visualAgentReady">Visual agent not ready</v-list-item-subtitle>
            </v-list-item>
            <v-divider v-if="assetMenu.context.asset_type === 'avatar'"></v-divider>
            <v-list-item
                v-if="assetMenu.context.asset_type === 'avatar'"
                prepend-icon="mdi-account-check"
                @click="handleDetermineBestAvatar"
            >
                <v-list-item-title>Auto-select portrait</v-list-item-title>
                <v-list-item-subtitle class="text-wrap">
                    May generate new portrait if no fitting portrait exists
                </v-list-item-subtitle>
            </v-list-item>
            <v-list-item
                v-if="assetMenu.context.asset_type === 'avatar'"
                :disabled="!visualAgentReady"
                prepend-icon="mdi-image-plus"
                @click="handleGenerateNewAvatar"
            >
                <v-list-item-title>Generate new portrait</v-list-item-title>
                <v-list-item-subtitle v-if="!visualAgentReady">Visual agent not ready</v-list-item-subtitle>
            </v-list-item>
            <v-list-item
                v-if="assetMenu.context.asset_type === 'avatar'"
                prepend-icon="mdi-image-multiple"
                @click="handleOpenAvatarSelect"
            >
                <v-list-item-title>Select portrait</v-list-item-title>
                <v-list-item-subtitle class="text-wrap">
                    Choose from existing portraits for this character
                </v-list-item-subtitle>
            </v-list-item>
            <v-divider v-if="assetMenu.context.asset_type === 'scene_illustration'"></v-divider>
            <v-list-item
                v-if="assetMenu.context.asset_type === 'scene_illustration'"
                prepend-icon="mdi-image-multiple"
                @click="handleOpenIllustrationSelect"
            >
                <v-list-item-title>Select illustration</v-list-item-title>
                <v-list-item-subtitle class="text-wrap">
                    Choose from existing scene illustrations
                </v-list-item-subtitle>
            </v-list-item>
            <v-divider v-if="assetMenu.context.asset_type === 'card'"></v-divider>
            <v-list-item
                v-if="assetMenu.context.asset_type === 'card'"
                prepend-icon="mdi-image-multiple"
                @click="handleOpenCardSelect"
            >
                <v-list-item-title>Select card</v-list-item-title>
                <v-list-item-subtitle class="text-wrap">
                    Choose from existing cards
                </v-list-item-subtitle>
            </v-list-item>
            <v-divider></v-divider>
            <v-list-item @click="handleClearImage">
                <template v-slot:prepend>
                    <v-icon color="delete">mdi-image-remove</v-icon>
                </template>
                <v-list-item-title>Clear Image</v-list-item-title>
                <v-list-item-subtitle>Remove image from this message</v-list-item-subtitle>
            </v-list-item>
            <v-list-item @click="handleDeleteImage">
                <template v-slot:prepend>
                    <v-icon color="delete">mdi-close-box-outline</v-icon>
                </template>
                <v-list-item-title>Delete Image</v-list-item-title>
                <v-list-item-subtitle>Permanently delete this image</v-list-item-subtitle>
            </v-list-item>
        </v-list>
    </v-menu>

    <!-- Avatar Selection Dialog -->
    <v-dialog v-model="avatarSelectDialog.show" max-width="500">
        <v-card>
            <v-card-title>Select Portrait</v-card-title>
            <v-card-text>
                <div v-if="avatarSelectDialog.assetIds.length === 0" class="text-center text-medium-emphasis py-8">
                    <v-icon size="48" color="grey">mdi-image-off-outline</v-icon>
                    <p class="mt-2">No portraits available for this character</p>
                </div>
                <VisualReferenceCarousel
                    v-else
                    v-model="avatarSelectDialog.selectedAssetId"
                    :asset-ids="avatarSelectDialog.assetIds"
                    :assets-map="assetsMap"
                    :base64-by-id="avatarSelectDialog.base64ById"
                    aspect="square"
                    label="Portrait:"
                />
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn text @click="closeAvatarSelectDialog">Cancel</v-btn>
                <v-btn 
                    color="primary" 
                    @click="confirmAvatarSelection"
                    :disabled="!avatarSelectDialog.selectedAssetId || avatarSelectDialog.assetIds.length === 0"
                >
                    Select
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

    <!-- Scene Illustration Selection Dialog -->
    <v-dialog v-model="illustrationSelectDialog.show" max-width="500">
        <v-card>
            <v-card-title>Select Scene Illustration</v-card-title>
            <v-card-text>
                <div v-if="illustrationSelectDialog.assetIds.length === 0" class="text-center text-medium-emphasis py-8">
                    <v-icon size="48" color="grey">mdi-image-off-outline</v-icon>
                    <p class="mt-2">No scene illustrations available</p>
                </div>
                <VisualReferenceCarousel
                    v-else
                    v-model="illustrationSelectDialog.selectedAssetId"
                    :asset-ids="illustrationSelectDialog.assetIds"
                    :assets-map="assetsMap"
                    :base64-by-id="illustrationSelectDialog.base64ById"
                    aspect="wide"
                    label="Illustration:"
                />
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn text @click="closeIllustrationSelectDialog">Cancel</v-btn>
                <v-btn 
                    color="primary" 
                    @click="confirmIllustrationSelection"
                    :disabled="!illustrationSelectDialog.selectedAssetId || illustrationSelectDialog.assetIds.length === 0"
                >
                    Select
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

    <!-- Card Selection Dialog -->
    <v-dialog v-model="cardSelectDialog.show" max-width="500">
        <v-card>
            <v-card-title>Select Card</v-card-title>
            <v-card-text>
                <div v-if="cardSelectDialog.assetIds.length === 0" class="text-center text-medium-emphasis py-8">
                    <v-icon size="48" color="grey">mdi-image-off-outline</v-icon>
                    <p class="mt-2">No cards available</p>
                </div>
                <VisualReferenceCarousel
                    v-else
                    v-model="cardSelectDialog.selectedAssetId"
                    :asset-ids="cardSelectDialog.assetIds"
                    :assets-map="assetsMap"
                    :base64-by-id="cardSelectDialog.base64ById"
                    aspect="square"
                    label="Card:"
                />
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn text @click="closeCardSelectDialog">Cancel</v-btn>
                <v-btn 
                    color="primary" 
                    @click="confirmCardSelection"
                    :disabled="!cardSelectDialog.selectedAssetId || cardSelectDialog.assetIds.length === 0"
                >
                    Select
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

    <!-- Delete Image Confirmation -->
    <ConfirmActionPrompt
        ref="deleteImageConfirm"
        action-label="Delete Image"
        description="Are you sure you want to permanently delete this image? This action cannot be undone."
        icon="mdi-close-box-outline"
        color="delete"
        :max-width="420"
        @confirm="confirmDeleteImage"
    />

    <!-- Insert Time Passage Dialog -->
    <v-dialog v-model="insertTimePassageDialog" max-width="400">
        <v-card>
            <v-card-title class="text-body-1">Insert Time Passage</v-card-title>
            <v-card-text>
                <p class="text-caption text-medium-emphasis mb-3">
                    Will be inserted after the selected message.
                </p>
                <div class="d-flex align-center">
                    <v-number-input v-model="insertTimePassageAmount" :min="1" label="Amount"
                        style="max-width: 180px" hide-details="auto" />
                    <v-select v-model="insertTimePassageUnit" :items="insertTimePassageUnits" label="Unit"
                        style="max-width: 180px" hide-details="auto" class="ml-2" />
                </div>
            </v-card-text>
            <v-card-actions>
                <v-spacer />
                <v-btn variant="text" @click="insertTimePassageDialog = false">Cancel</v-btn>
                <v-btn color="primary" @click="submitInsertTimePassage">Insert</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

    <div class="message-container mb-8" ref="messageContainer" style="flex-grow: 1; overflow-y: auto;" @click="onMessageContainerClick">
        <div v-for="(message, index) in messages" :key="message.id != null ? `${message.type}-${message.id}` : `idx-${index}`" class="message-wrapper">
            <div v-if="message.type === 'character' || message.type === 'processing_input'"
                :class="`message ${message.type}`" :id="`message-${message.id}`" :style="{ borderColor: message.color }">
                <div class="character-message">
                    <CharacterMessage :character="message.character" :text="message.text" :color="message.color" :message_id="message.id" :uxLocked="uxLocked" :appBusy="appBusy" :ttsAvailable="ttsAvailable" :ttsBusy="ttsBusy" :isLastMessage="index === messages.length - 1" :editorRevisionsEnabled="editorRevisionsEnabled" :editorRevisionMethod="editorRevisionMethod" :rev="message.rev || 0" :scene-rev="scene?.data?.rev || 0" :appearanceConfig="appearanceConfig" :scene="scene" :asset_id="message.asset_id" :asset_type="message.asset_type" :disable_avatar_fallback="message.disable_avatar_fallback || false" :revisionsCount="(message.revisions && message.revisions.length) || 0" :revisionIndex="message.revision_index || 0" :revisionSource="revisionCurrentSource(message)" :revisionReason="revisionCurrentReason(message)" :revisionBusy="message.regenerating || false" :entityMentions="getEntityMentionsForMessage(message.id)" @navigate-revision="(dir) => navigateRevision(message.id, dir)" />
                </div>
            </div>
            <div v-else-if="message.type === 'request_input' && message.choices">
                <v-alert variant="tonal" type="info"  class="system-message mb-3">
                    {{ message.text }}
                </v-alert>
                <div>
                    <v-radio-group inline class="radio-group" v-if="!message.multiSelect" v-model="message.selectedChoices" :disabled="message.sent">
                        <div v-for="(choice, index) in message.choices" :key="index">
                            <v-radio :key="index" :label="choice" :value="choice"></v-radio>
                        </div>
                    </v-radio-group>
                    <div v-else  class="choice-buttons">
                        <div v-for="(choice, index) in message.choices" :key="index">
                            <v-checkbox :label="choice" v-model="message.selectedChoices" :value="choice" :disabled="message.sent"></v-checkbox>
                        </div>
                    </div>
                    <div class="mb-3">
                        <v-btn v-if="!message.sent" @click="sendAllChoices(message)" color="secondary" :disabled="message.sent">Continue</v-btn>
                    </div>
                </div>
            </div>
            <div v-else-if="message.type === 'system'" :class="`message ${message.type}`">
                <SystemMessage 
                    :message="message.text" 
                    :message-id="message.id"
                    :color="message.meta.color" 
                    :icon="message.meta.icon" 
                    :title="message.meta.title" 
                    :display="message.meta.display" 
                    :as_markdown="message.meta.as_markdown"
                    @close="closeSystemMessage"
                />
            </div>
            <div v-else-if="message.type === 'status'" :class="`message ${message.type}`">
                <div class="narrator-message">
                    <StatusMessage :text="message.text" :status="message.status" :isLastMessage="index === messages.length - 1" />
                </div>
            </div>
            <div v-else-if="message.type === 'narrator'" :class="`message ${message.type}`">
                <div class="narrator-message"  :id="`message-${message.id}`">
                    <NarratorMessage :text="message.text" :message_id="message.id" :uxLocked="uxLocked" :appBusy="appBusy" :isLastMessage="index === messages.length - 1" :editorRevisionsEnabled="editorRevisionsEnabled" :editorRevisionMethod="editorRevisionMethod" :ttsAvailable="ttsAvailable" :ttsBusy="ttsBusy" :rev="message.rev || 0" :scene-rev="scene?.data?.rev || 0" :appearanceConfig="appearanceConfig" :asset_id="message.asset_id" :asset_type="message.asset_type" :revisionsCount="(message.revisions && message.revisions.length) || 0" :revisionIndex="message.revision_index || 0" :revisionSource="revisionCurrentSource(message)" :revisionReason="revisionCurrentReason(message)" :revisionBusy="message.regenerating || false" :entityMentions="getEntityMentionsForMessage(message.id)" @navigate-revision="(dir) => navigateRevision(message.id, dir)" />
                </div>
            </div>
            <div v-else-if="message.type === 'director' && !getMessageTypeHidden(message.type)" :class="`message ${message.type}`">
                <div class="director-message"  :id="`message-${message.id}`">
                    <DirectorMessage :text="message.text" :message_id="message.id" :character="message.character" :direction_mode="message.direction_mode" :action="message.action" :subtype="message.subtype" :uxLocked="uxLocked" :isLastMessage="index === messages.length - 1"/>
                </div>
            </div>
            <div v-else-if="message.type === 'time'" :class="`message ${message.type}`">
                <div class="time-message"  :id="`message-${message.id}`">
                    <TimePassageMessage :text="message.text" :message_id="message.id" :ts="message.ts" :uxLocked="uxLocked" :appBusy="appBusy" :isLastMessage="index === messages.length - 1" />
                </div>
            </div>
            <div v-else-if="message.type === 'player_choice'" :class="`message ${message.type}`">
                <div class="player-choice-message"  :id="`message-player-choice`">
                    <PlayerChoiceMessage :choices="message.data.choices" :character="message.data.character" @close="closePlayerChoice" :uxLocked="uxLocked" :isLastMessage="index === messages.length - 1" />
                </div>
            </div>
            <div v-else-if="message.type === 'ux'" :class="`message ${message.type}`">
                <div class="ux-element-message" :id="`message-ux-${message.id}`">
                    <UxElementMessage :element="message.element" :uxLocked="uxLocked" :appearanceConfig="appearanceConfig" @close="closeUxElement" />
                </div>
            </div>
            <div v-else-if="message.type === 'context_investigation' && !getMessageTypeHidden(message.type)" :class="`message ${message.type}`">
                <div class="context-investigation-message"  :id="`message-${message.id}`">
                    <ContextInvestigationMessage :message="message" :uxLocked="uxLocked" :appBusy="appBusy" :isLastMessage="index === messages.length - 1" :editorRevisionsEnabled="editorRevisionsEnabled" :editorRevisionMethod="editorRevisionMethod" :ttsAvailable="ttsAvailable" :ttsBusy="ttsBusy" :appearanceConfig="appearanceConfig" :asset_id="message.asset_id" :asset_type="message.asset_type" :revisionsCount="(message.revisions && message.revisions.length) || 0" :revisionIndex="message.revision_index || 0" :revisionSource="revisionCurrentSource(message)" :revisionReason="revisionCurrentReason(message)" :revisionBusy="message.regenerating || false" :entityMentions="getEntityMentionsForMessage(message.id)" @navigate-revision="(dir) => navigateRevision(message.id, dir)" />
                </div>
            </div>

            <div v-else-if="!getMessageTypeHidden(message.type)" :class="`message ${message.type}`">
                {{ message.text }}
            </div>
        </div>
        <EntityTooltip
            :model-value="entityTooltip.open"
            :activator="entityTooltip.activator"
            :entity="entityTooltip.entity"
            @update:model-value="onEntityTooltipUpdate"
            @configure-highlights="onConfigureEntityHighlights"
            @examine="triggerExamineEntity"
            @look-at="triggerLookAtEntity"
        />
    </div>
</template>

<script>
import CharacterMessage from './CharacterMessage.vue';
import NarratorMessage from './NarratorMessage.vue';
import DirectorMessage from './DirectorMessage.vue';
import TimePassageMessage from './TimePassageMessage.vue';
import StatusMessage from './StatusMessage.vue';
import RequestInput from './RequestInput.vue';
import PlayerChoiceMessage from './PlayerChoiceMessage.vue';
import UxElementMessage from './UxElementMessage.vue';
import ContextInvestigationMessage from './ContextInvestigationMessage.vue';
import SystemMessage from './SystemMessage.vue';
import VisualReferenceCarousel from './VisualReferenceCarousel.vue';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import EntityHighlightMixin from './EntityHighlightMixin.js';
import VisualAssetsMixin from './VisualAssetsMixin.js';
import RevisionStackMixin from './RevisionStackMixin.js';
import { isVisualAgentReady, VIS_TYPE } from '@/constants/visual';
import { isKnownSceneCharacter } from '@/utils/entityActions';
import { primaryModifierLabel } from '@/utils/keyboardModifiers';
import {
    getMessageColor as resolveMessageColor,
    getMessageStyle as resolveMessageStyle,
} from '@/utils/messageColors.js';

const MESSAGE_FLAGS = {
    NONE: 0,
    HIDDEN: 1,
}

const ASSET_SELECT_TYPES = {
    avatar: {
        dialogKey: 'avatarSelectDialog',
        requiresCharacter: true,
        getAssetIds(vm, ctx) {
            const avatars = vm.getCharacterAssets(ctx.character, VIS_TYPE.CHARACTER_PORTRAIT);
            return avatars.map(a => a.id);
        },
        buildUpdateMessage(dialog) {
            return {
                type: 'scene_assets',
                action: 'update_message_asset',
                asset_id: dialog.selectedAssetId,
                message_id: dialog.messageId,
                character_name: dialog.characterName,
            };
        },
        reset(dialog) {
            dialog.show = false;
            dialog.characterName = null;
            dialog.messageId = null;
            dialog.assetIds = [];
            dialog.selectedAssetId = null;
            dialog.base64ById = {};
        },
    },
    scene_illustration: {
        dialogKey: 'illustrationSelectDialog',
        requiresCharacter: false,
        getAssetIds(vm) {
            return Object.entries(vm.assetsMap)
                .filter(([, asset]) => {
                    const meta = asset?.meta || {};
                    return meta.vis_type === VIS_TYPE.SCENE_ILLUSTRATION || meta.vis_type === VIS_TYPE.SCENE_BACKGROUND;
                })
                .map(([id]) => id);
        },
        buildUpdateMessage(dialog) {
            return {
                type: 'scene_assets',
                action: 'update_message_asset',
                asset_id: dialog.selectedAssetId,
                message_id: dialog.messageId,
            };
        },
        reset(dialog) {
            dialog.show = false;
            dialog.messageId = null;
            dialog.assetIds = [];
            dialog.selectedAssetId = null;
            dialog.base64ById = {};
        },
    },
    card: {
        dialogKey: 'cardSelectDialog',
        requiresCharacter: false,
        getAssetIds(vm) {
            return Object.entries(vm.assetsMap)
                .filter(([, asset]) => {
                    const meta = asset?.meta || {};
                    return meta.vis_type === VIS_TYPE.CHARACTER_CARD || meta.vis_type === VIS_TYPE.SCENE_CARD;
                })
                .map(([id]) => id);
        },
        buildUpdateMessage(dialog) {
            return {
                type: 'scene_assets',
                action: 'update_message_asset',
                asset_id: dialog.selectedAssetId,
                message_id: dialog.messageId,
            };
        },
        reset(dialog) {
            dialog.show = false;
            dialog.messageId = null;
            dialog.assetIds = [];
            dialog.selectedAssetId = null;
            dialog.base64ById = {};
        },
    },
}

const ASSET_SELECT_DIALOG_KEYS = Object.values(ASSET_SELECT_TYPES).map(t => t.dialogKey)

export default {
    name: 'SceneMessages',
    mixins: [VisualAssetsMixin, RevisionStackMixin, EntityHighlightMixin],
    props: {
        appearanceConfig: {
            type: Object,
        },
        uxLocked: {
            type: Boolean,
            default: false,
        },
        appBusy: {
            type: Boolean,
            default: false,
        },
        agentStatus: {
            type: Object,
        },
        audioPlayedForMessageId: {
            default: undefined,
        },
        scene: {
            type: Object,
        }
    },
    components: {
        CharacterMessage,
        NarratorMessage,
        DirectorMessage,
        TimePassageMessage,
        StatusMessage,
        RequestInput,
        PlayerChoiceMessage,
        UxElementMessage,
        ContextInvestigationMessage,
        SystemMessage,
        VisualReferenceCarousel,
        ConfirmActionPrompt,
    },
    emits: ['cancel-audio-queue', 'configure-entity-highlights'],
    data() {
        return {
            primaryModifierLabel,
            messages: [],
            selectedForkMessageId: null,
            // Track last effective asset ID per scope for "on_change" cadence
            lastEffectiveAssetIdByScope: {},
            // Debounce timer for reapplyMessageAssetCadence
            _reapplyDebounceTimer: null,
            // Centralized cache for loaded asset data (base64 images)
            // Keyed by asset_id -> { base64: string, mediaType: string }
            assetCache: {},
            // Shared asset menu state
            assetMenu: {
                show: false,
                location: 'bottom',
                target: null,
                context: {
                    asset_id: null,
                    asset_type: null,
                    character: null,
                    message_content: null,
                    message_id: null,
                    imageSrc: null,
                },
            },
            // Track which message IDs are currently processing asset operations
            processingAssetMessageIds: new Set(),
            // Context-investigation messages awaiting a freshly requested visual.
            // Drives the toolbar "Visualize" spinner until the asset attaches
            // (message_asset_update) or the visual operation finishes.
            visualizingMessageIds: new Set(),
            // Avatar selection dialog state
            avatarSelectDialog: {
                show: false,
                characterName: null,
                messageId: null,
                assetIds: [],
                selectedAssetId: null,
                base64ById: {},
            },
            // Scene illustration selection dialog state
            illustrationSelectDialog: {
                show: false,
                messageId: null,
                assetIds: [],
                selectedAssetId: null,
                base64ById: {},
            },
            // Card selection dialog state
            cardSelectDialog: {
                show: false,
                messageId: null,
                assetIds: [],
                selectedAssetId: null,
                base64ById: {},
            },
            // Insert time passage dialog state
            insertTimePassageDialog: false,
            insertTimePassageMessageId: null,
            insertTimePassageAmount: 1,
            insertTimePassageUnit: 'hours',
            insertTimePassageUnits: ['minutes', 'hours', 'days', 'weeks', 'months', 'years'],
            // id of the message awaiting an editor revision (its spinner is
            // cleared on the editor `operation_done` envelope, which has no id)
            revisionPendingId: null,
        }
    },
    computed: {
        messageAssetsConfig() {
            return this.appearanceConfig?.scene?.message_assets || null;
        },
        editorRevisionsEnabled() {
            return this.agentStatus && this.agentStatus.editor && this.agentStatus.editor.actions && this.agentStatus.editor.actions["revision"] && this.agentStatus.editor.actions["revision"].enabled;
        },
        editorRevisionMethod() {
            return this.agentStatus?.editor?.actions?.revision?.config?.revision_method?.value || null;
        },
        ttsAvailable() {
            return this.agentStatus.tts?.available;
        },
        ttsBusy() {
            return this.agentStatus.tts?.busy || this.agentStatus.tts?.busy_bg;
        },
        visualAgentReady() {
            return isVisualAgentReady(this.agentStatus);
        },
        assetMenuStyle() {
            // Position the menu absolutely at the target location
            return {
                position: 'fixed',
            };
        },
        assetSupportsRegeneration() {
            // Check if the current asset menu context supports regeneration
            const assetType = this.assetMenu.context.asset_type;
            return assetType === 'card' || assetType === 'scene_illustration';
        },
        forkInstructions() {
            if (!this.selectedForkMessageId) {
                return "A new copy of the scene will be forked from the message you've selected.";
            }

            const message = this.messages.find(m => m.id === this.selectedForkMessageId);
            const rev = message ? (message.rev || 0) : 0;
            const isReconstructive = rev > 0;

            let instructions = isReconstructive
                ? "Creating a reconstructive fork: The scene will be reconstructed to the exact revision of the selected message, preserving all world state and character details as they were at that point."
                : "Creating a shallow fork: All progress after the selected message will be removed. This may require manual cleanup of world state and character details in complex scenes.";

            // Add shared context disconnection warning if scene has shared context
            if (this.scene?.data?.shared_context) {
                instructions += "\n\n⚠️ Note: The forked scene will be disconnected from its shared context since shared world context cannot be reconstructed to a specific revision.";
            }

            return instructions;
        },
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput', 'beginUxInteraction', 'endUxInteraction', 'clearUxInteractions', 'requestSceneAssets', 'openVisualLibraryWithAsset'],
    provide() {
        return {
            requestDeleteMessage: this.requestDeleteMessage,
            requestRegenerateLastMessage: this.requestRegenerateLastMessage,
            createPin: this.createPin,
            forkSceneInitiate: this.forkSceneInitiate,
            getMessageColor: this.getMessageColor,
            getMessageStyle: this.getMessageStyle,
            reviseMessage: this.reviseMessage,
            generateTTS: this.generateTTS,
            // Provide getter for centralized asset cache (used by MessageAssetImage)
            getAssetFromCache: (assetId) => this.assetCache[assetId] || null,
            // Provide method to show the shared asset menu
            showAssetMenu: this.showAssetMenu,
            // Provide method to check if asset is processing
            isAssetProcessing: this.isAssetProcessing,
            // Provide method to mark message as processing
            markAssetProcessing: this.markAssetProcessing,
            // Provide method to open insert time passage dialog
            insertTimePassage: this.insertTimePassage,
            // Generate a visual asset for a context-investigation message
            visualizeMessage: this.visualizeMessage,
            isMessageVisualizing: this.isMessageVisualizing,
        }
    },
    methods: {

        getMessageColor(typ) {
            return resolveMessageColor(this.appearanceConfig, typ);
        },

        getMessageTypeHidden(typ) {
            // messages are hidden if appearanceCOnfig.scene[`${typ}_messages`].show is false
            // true and undefined are the same

            if(!this.appearanceConfig || !this.appearanceConfig.scene[`${typ}_messages`]) {
                return false;
            } else if(this.appearanceConfig && this.appearanceConfig.scene[`${typ}_messages`].show === false) {
                return true;
            }

            return false;
        },

        getMessageStyle(typ) {
            return resolveMessageStyle(this.appearanceConfig, typ);
        },

        clear() {
            this.messages = [];
            this.lastEffectiveAssetIdByScope = {};
            this.assetCache = {};
            this.processingAssetMessageIds.clear();
            // Clear any pending debounce timer
            if (this._reapplyDebounceTimer) {
                clearTimeout(this._reapplyDebounceTimer);
                this._reapplyDebounceTimer = null;
            }
            // Clear UX interaction tracking
            if (this.clearUxInteractions) {
                this.clearUxInteractions();
            }
        },

        /**
         * Centralized handler for asset-related WebSocket messages.
         * Handles scene_asset (asset data) and message_asset_update (dynamic avatar changes).
         */
        handleAssetMessages(data) {
            // Handle scene_asset messages - cache the loaded asset data
            if (data.type === 'scene_asset' && data.asset_id) {
                this.assetCache = {
                    ...this.assetCache,
                    [data.asset_id]: {
                        base64: data.asset,
                        mediaType: data.media_type || 'image/png',
                    }
                };
                
                // Update any open asset-select dialogs that reference this asset
                ASSET_SELECT_DIALOG_KEYS.forEach((dialogKey) => {
                    const dialog = this[dialogKey];
                    if (!dialog?.show) {
                        return;
                    }
                    const ids = dialog.assetIds || [];
                    if (Array.isArray(ids) && ids.includes(data.asset_id)) {
                        dialog.base64ById = {
                            ...(dialog.base64ById || {}),
                            [data.asset_id]: data.asset,
                        };
                    }
                });
            }
            
            // Handle message_asset_update - update a message's asset_id dynamically
            if (data.type === 'message_asset_update' && data.message_id) {
                const msg = this.messages.find(m => m.id === data.message_id);
                if (msg) {
                    msg.asset_id = data.asset_id || null;
                    msg.asset_type = data.asset_type || null;
                    // Update raw fields so reapplyMessageAssetCadence uses the new values
                    msg.raw_asset_id = data.asset_id || null;
                    msg.raw_asset_type = data.asset_type || null;

                    // Request the new asset if not already cached
                    if (msg.asset_id && this.requestSceneAssets && !this.assetCache[msg.asset_id]) {
                        this.requestSceneAssets([msg.asset_id]);
                    }
                    // Clear processing state for this message
                    this.processingAssetMessageIds.delete(data.message_id);
                    this.visualizingMessageIds.delete(data.message_id);
                }
            }

            // The visual operation finished — clear any toolbar "Visualize"
            // spinners that won't be cleared by an asset attaching (e.g.
            // prompt-only mode or a generation error).
            if (data.type === 'visual' && data.action === 'operation_done' && this.visualizingMessageIds.size) {
                this.visualizingMessageIds.clear();
            }
            
            // Handle determine_avatar_noop - world state agent decided no action needed
            if (data.action === 'determine_avatar_noop') {
                const messageIds = data.message_ids || [];
                // Clear processing state for all affected messages
                messageIds.forEach(msgId => {
                    this.processingAssetMessageIds.delete(msgId);
                });
            }

            // Handle default avatar changes - reapply cadence to update message avatars
            if (data.type === 'scene_asset_character_avatar') {
                // Debounce to allow scene data to update first (in parent component)
                if (this._reapplyDebounceTimer) {
                    clearTimeout(this._reapplyDebounceTimer);
                }
                this._reapplyDebounceTimer = setTimeout(() => {
                    this.reapplyMessageAssetCadence();
                    this._reapplyDebounceTimer = null;
                }, 50);
            }
        },
        
        /**
         * Compute the effective avatar ID that "Always" cadence would show.
         * Prefers message.asset_id if present, otherwise falls back to character's default avatar.
         */
        computeEffectiveAvatarId(characterName, messageAssetId) {
            // Prefer explicit message asset_id if present
            if (messageAssetId) {
                return messageAssetId;
            }
            // Fall back to character's default avatar from scene data
            if (this.scene?.data?.characters) {
                const char = this.scene.data.characters.find(c => c.name === characterName);
                if (char?.avatar) {
                    return char.avatar;
                }
            }
            // Also check inactive characters
            if (this.scene?.data?.inactive_characters) {
                const char = Object.values(this.scene.data.inactive_characters).find(c => c.name === characterName);
                if (char?.avatar) {
                    return char.avatar;
                }
            }
            return null;
        },
        
        /**
         * Apply cadence logic to determine if asset should be rendered.
         * Returns { shouldShow: boolean, effectiveAssetId: string|null, disableFallback: boolean }
         */
        applyAssetCadence(assetType, characterName, messageAssetId) {
            // Get cadence config for this asset type
            const cadenceConfig = this.appearanceConfig?.scene?.message_assets?.[assetType];
            const cadence = cadenceConfig?.cadence || 'always';
            
            // Compute effective asset ID (what "Always" would show)
            let effectiveAssetId = null;
            if (assetType === 'avatar') {
                effectiveAssetId = this.computeEffectiveAvatarId(characterName, messageAssetId);
            } else {
                // For future asset types, use message asset_id directly
                effectiveAssetId = messageAssetId || null;
            }
            
            // Determine scope key for tracking
            let scopeKey = null;
            if (assetType === 'avatar') {
                scopeKey = `avatar:${characterName}`;
            } else {
                // For future global asset types (e.g., scene_illustration)
                scopeKey = `${assetType}:global`;
            }
            
            // Apply cadence logic
            if (cadence === 'always') {
                // Always show: return effective asset ID, allow fallback
                return {
                    shouldShow: true,
                    effectiveAssetId: effectiveAssetId,
                    disableFallback: false,
                };
            } else if (cadence === 'never') {
                // Never show: clear asset, disable fallback
                // Still update tracking for correct future comparisons
                if (scopeKey) {
                    this.lastEffectiveAssetIdByScope[scopeKey] = effectiveAssetId;
                }
                return {
                    shouldShow: false,
                    effectiveAssetId: null,
                    disableFallback: true,
                };
            } else if (cadence === 'on_change') {
                // On change: show if first message for this scope OR asset changed
                const lastEffectiveId = scopeKey ? this.lastEffectiveAssetIdByScope[scopeKey] : undefined;
                const isFirstMessage = lastEffectiveId === undefined;
                const hasChanged = effectiveAssetId !== lastEffectiveId;
                
                // Update tracking (always, even if not showing)
                if (scopeKey) {
                    this.lastEffectiveAssetIdByScope[scopeKey] = effectiveAssetId;
                }
                
                if (isFirstMessage || hasChanged) {
                    // Show: return effective asset ID, disable fallback (we're explicitly setting it)
                    return {
                        shouldShow: true,
                        effectiveAssetId: effectiveAssetId,
                        disableFallback: false,
                    };
                } else {
                    // Don't show: clear asset, disable fallback
                    return {
                        shouldShow: false,
                        effectiveAssetId: null,
                        disableFallback: true,
                    };
                }
            }
            
            // Default fallback
            return {
                shouldShow: true,
                effectiveAssetId: effectiveAssetId,
                disableFallback: false,
            };
        },
        
        /**
         * Reapply cadence logic to all already-rendered character messages.
         * Called when appearanceConfig changes to update existing messages immediately.
         */
        reapplyMessageAssetCadence() {
            // Reset tracking map - we'll rebuild it by processing messages in order
            this.lastEffectiveAssetIdByScope = {};

            // Process each message in order to rebuild tracking state correctly
            for (let i = 0; i < this.messages.length; i++) {
                const msg = this.messages[i];

                // Only process character messages
                if (msg.type !== 'character') {
                    continue;
                }

                // Get raw asset fields (fallback to null if not stored - for messages created before this feature)
                const rawAssetId = msg.raw_asset_id !== undefined ? msg.raw_asset_id : null;
                const rawAssetType = msg.raw_asset_type !== undefined ? msg.raw_asset_type : null;

                // Check if this message has a non-avatar asset type
                const hasNonAvatarAsset = rawAssetType && rawAssetType !== 'avatar';

                if (hasNonAvatarAsset) {
                    // Non-avatar asset (e.g., scene_illustration, card) - don't apply avatar cadence
                    // Just restore the raw asset values
                    msg.asset_id = rawAssetId;
                    msg.asset_type = rawAssetType;
                    msg.disable_avatar_fallback = false;
                } else {
                    // Avatar or no asset - apply cadence logic for avatars
                    const cadenceResult = this.applyAssetCadence('avatar', msg.character, rawAssetId);

                    // Update render fields
                    msg.asset_id = cadenceResult.effectiveAssetId;
                    msg.asset_type = cadenceResult.shouldShow ? 'avatar' : null;
                    msg.disable_avatar_fallback = cadenceResult.disableFallback;
                }
            }

            // Force Vue reactivity by replacing the array
            this.messages = [...this.messages];
        },

        createPin(message_id){
            this.getWebsocket().send(JSON.stringify({ type: 'world_state_agent', action: 'summarize_and_pin', message_id }));
        },

        requestDeleteMessage(message_id) {
            this.getWebsocket().send(JSON.stringify({ type: 'scene_message', action: 'delete', id: message_id }));
        },

        // Mark the most recent revision-supporting message as
        // `regenerating` so its pager spinner kicks in immediately. The
        // flag is cleared on the matching `message_edited`
        // (reason=regenerate) or `regenerate_failed` event. Returns true
        // when a slot was flagged, false when there is nothing to
        // regenerate so callers can skip the backend round-trip.
        //
        // Heuristic: walks back from the tail and picks the first
        // revisable type. The backend's `regenerate_target_message` only
        // skips trailing reinforcement messages; this picks the first
        // character/narrator/context_investigation. Other message types
        // (time, system, status, etc.) at the tail would mismatch the
        // backend's target — in that case the catch-all
        // `assistant.regenerate_failed` handler clears every flagged
        // slot, self-correcting the divergence.
        //
        // The scene intro renders through NarratorMessage.vue but is not
        // a real scene message (it carries no id and isn't in scene
        // history), so it's never a regen target — skip id-less slots.
        requestRegenerateLastMessage() {
            for (let i = this.messages.length - 1; i >= 0; i--) {
                const m = this.messages[i];
                if (this.revisionSupportedType(m.type) && m.id) {
                    m.regenerating = true;
                    return true;
                }
            }
            return false;
        },

        handleChoiceInput(data) {
            // Create a new message with buttons for the choices
            const message = {
                id: data.id,
                type: data.type,
                text: data.message,
                choices: data.data.choices,
                selectedChoices: data.data.default || (data.data.multi_select ? [] : null),
                multiSelect: data.data.multi_select,
                color: data.color,
                sent: false,
                ts: data.ts,
            };
            this.messages.push(message);
        },

        sendChoice(message, choice) {
            const index = message.selectedChoices.indexOf(choice);
            if (index === -1) {
                // If the checkbox is checked, add the choice to the selectedChoices array
                message.selectedChoices.push(choice);
            } else {
                // If the checkbox is unchecked, remove the choice from the selectedChoices array
                message.selectedChoices.splice(index, 1);
            }
        },

        sendAllChoices(message) {

            let text;

            if(message.multiSelect) {
                text = message.selectedChoices.join(', ');
            } else {
                text = message.selectedChoices;
            }

            // Send all selected choices to the server
            this.getWebsocket().send(JSON.stringify({ type: 'interact', text: text }));
            // Clear the selectedChoices array
            message.sent = true;
            this.setWaitingForInput(false);
        },

        messageTypeAllowsAudio(type) {
            return [ 
                'narrator',
                'character',
                'context_investigation',
            ].includes(type);
        },

        messageTypeIsSceneMessage(type) {
            return ![ 
                'request_input', 
                'client_status', 
                'agent_status',
                'agent_message',
                'assistant',
                'status', 
                'autocomplete_suggestion',
                'rate_limited',
                'rate_limit_reset',
                'generation_error',
            ].includes(type);
        },

        closePlayerChoice() {
            // find the most recent player choice message and remove it
            for (let i = this.messages.length - 1; i >= 0; i--) {
                if (this.messages[i].type === 'player_choice') {
                    this.messages.splice(i, 1);
                    break;
                }
            }
        },

        closeSystemMessage(messageId) {
            // Remove the system message with the given id from the messages array
            if (messageId) {
                const index = this.messages.findIndex(m => m.id === messageId && m.type === 'system');
                if (index !== -1) {
                    this.messages.splice(index, 1);
                }
            } else {
                // If no messageId provided, remove the most recent system message
                for (let i = this.messages.length - 1; i >= 0; i--) {
                    if (this.messages[i].type === 'system') {
                        this.messages.splice(i, 1);
                        break;
                    }
                }
            }
        },

        closeUxElement(uxId) {
            // Track which UX IDs we're closing for interaction tracking
            const closedIds = [];
            
            // remove the most recent ux message matching this id (or any ux message if id missing)
            for (let i = this.messages.length - 1; i >= 0; i--) {
                if (this.messages[i].type === 'ux') {
                    const msgId = this.messages[i].id || this.messages[i].element?.id;
                    if (!uxId || this.messages[i].id === uxId || this.messages[i].element?.id === uxId) {
                        if (msgId) {
                            closedIds.push(msgId);
                        }
                        this.messages.splice(i, 1);
                        if (uxId) {
                            // If specific uxId provided, only remove one
                            break;
                        }
                    }
                }
            }
            
            // End UX interaction tracking for closed elements
            if (this.endUxInteraction) {
                if (uxId) {
                    this.endUxInteraction(uxId);
                    // If the rendered message id differs from uxId, also end by the actual removed id
                    if (closedIds.length > 0 && closedIds[0] && closedIds[0] !== uxId) {
                        this.endUxInteraction(closedIds[0]);
                    }
                } else if (closedIds.length > 0) {
                    // If no specific uxId, clear all (fallback safety)
                    if (this.clearUxInteractions) {
                        this.clearUxInteractions();
                    }
                }
            }
        },

        forkSceneInitiate(message_id) {
            this.selectedForkMessageId = message_id;
            this.$refs.requestForkName.openDialog(
                { message_id: message_id }
            );
        },

        forkScene(message_id, save_name) {
            this.getWebsocket().send(JSON.stringify({ 
                type: 'assistant',
                action: 'fork_new_scene',
                message_id: message_id,
                save_name: save_name,
            }));
        },

        reviseMessage(message_id) {
            // `regenerating` is overloaded boolean|string: a string doubles
            // as the spinner verb ('Revising' vs the default 'Regenerating').
            // Cleared on the `message_edited` (reason=revision) echo and, for
            // the no-op/failure/cancel paths, on the editor `operation_done`
            // envelope — which carries no id, so track the pending slot here.
            const idx = this.revisionFindSlotIndex(message_id);
            if (idx >= 0) {
                this.messages[idx].regenerating = 'Revising';
                this.revisionPendingId = message_id;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'editor',
                action: 'request_revision',
                message_id: message_id,
            }));
        },

        // Stop the revision spinner on the slot reviseMessage() flagged.
        clearRevisionPending() {
            if (this.revisionPendingId == null) return;
            const idx = this.revisionFindSlotIndex(this.revisionPendingId);
            if (idx >= 0) {
                this.messages[idx].regenerating = false;
            }
            this.revisionPendingId = null;
        },

        generateTTS(message_id) {
            this.getWebsocket().send(JSON.stringify({
                type: 'tts',
                action: 'generate_for_scene_message',
                message_id: message_id,
            }));
        },

        insertTimePassage(messageId) {
            this.insertTimePassageMessageId = messageId;
            this.insertTimePassageAmount = 1;
            this.insertTimePassageUnit = 'hours';
            this.insertTimePassageDialog = true;
        },

        isMessageVisualizing(messageId) {
            return this.visualizingMessageIds.has(messageId);
        },

        // Map a context-investigation message to the visual type that best
        // fits its subject, plus the instructions/character to seed the prompt.
        // Returns null for messages that have no fitting visual subject.
        buildVisualizeRequest(message) {
            const args = message.source_arguments || {};
            const instructions = message.text || "";
            switch (message.sub_type) {
                case 'examine': {
                    const kind = args.entity_kind;
                    const name = args.entity_name;
                    if (kind === 'item') return { vis_type: VIS_TYPE.OBJECT_ILLUSTRATION, instructions };
                    if (kind === 'place') return { vis_type: VIS_TYPE.SCENE_BACKGROUND, instructions };
                    if (kind === 'character') {
                        // Only real scene actors have the character data the
                        // CHARACTER_CARD generation requires; background
                        // characters fall back to a scene illustration.
                        if (isKnownSceneCharacter(this.scene?.data, name)) {
                            return { vis_type: VIS_TYPE.CHARACTER_CARD, character_name: name, instructions };
                        }
                        return { vis_type: VIS_TYPE.SCENE_ILLUSTRATION, instructions };
                    }
                    return null;
                }
                case 'visual-character':
                    return { vis_type: VIS_TYPE.CHARACTER_CARD, character_name: args.character, instructions };
                case 'visual-scene':
                    return { vis_type: VIS_TYPE.SCENE_ILLUSTRATION, instructions };
                default:
                    return null;
            }
        },

        visualizeMessage(message_id) {
            const message = this.messages.find(m => m.id === message_id);
            if (!message) return;
            const request = this.buildVisualizeRequest(message);
            if (!request) return;

            this.visualizingMessageIds.add(message_id);

            const payload = {
                type: 'visual',
                action: 'visualize',
                vis_type: request.vis_type,
                prompt_only: !this.visualAgentReady,
                save_asset: true,
                asset_allow_override: true,
                asset_allow_auto_attach: true,
                message_ids: [message_id],
            };
            if (request.character_name) {
                payload.character_name = request.character_name;
            }
            if (request.instructions) {
                payload.instructions = request.instructions;
            }
            this.getWebsocket().send(JSON.stringify(payload));
        },

        submitInsertTimePassage() {
            this.getWebsocket().send(JSON.stringify({
                type: 'time_passage',
                action: 'insert_after',
                message_id: this.insertTimePassageMessageId,
                amount: this.insertTimePassageAmount,
                unit: this.insertTimePassageUnit,
            }));
            this.insertTimePassageDialog = false;
        },

        /**
         * Show the asset menu for a given image context.
         * Called by child MessageAssetImage components.
         */
        showAssetMenu(event, context) {
            // Store the context (asset_id, asset_type, character, etc.)
            this.assetMenu.context = { ...context };
            
            // Set the target element for positioning
            this.assetMenu.target = event.currentTarget || event.target;
            
            // Show the menu
            this.assetMenu.show = true;
        },

        /**
         * Check if an asset is currently being processed
         */
        isAssetProcessing(messageId) {
            return this.processingAssetMessageIds.has(messageId);
        },

        /**
         * Mark a message as processing an asset operation
         */
        markAssetProcessing(messageId) {
            if (messageId) {
                this.processingAssetMessageIds.add(messageId);
            }
        },

        /**
         * Handle "View Image" menu option
         */
        handleViewImage() {
            // Close the menu
            this.assetMenu.show = false;
            
            // The context should have the imageSrc and we need to trigger
            // the AssetView in the MessageAssetImage component
            // For now, we'll emit this back through a callback if provided
            if (this.assetMenu.context.onViewImage) {
                this.assetMenu.context.onViewImage();
            }
        },

        /**
         * Handle "Open in Visual Library" menu option
         */
        handleOpenInVisualLibrary() {
            // Close the menu
            this.assetMenu.show = false;
            
            const assetId = this.assetMenu.context.asset_id;
            if (!assetId) return;
            
            // Use injected method from TalemateApp
            if (this.openVisualLibraryWithAsset && typeof this.openVisualLibraryWithAsset === 'function') {
                this.openVisualLibraryWithAsset(assetId);
            } else {
                console.warn('openVisualLibraryWithAsset not available');
            }
        },

        /**
         * Handle "Determine best avatar" menu option
         */
        handleDetermineBestAvatar() {
            // Close the menu
            this.assetMenu.show = false;
            
            const ctx = this.assetMenu.context;
            if (!ctx.character || !ctx.message_content || !ctx.message_id) {
                return;
            }

            // Mark this message as processing
            this.processingAssetMessageIds.add(ctx.message_id);

            const ws = this.getWebsocket();
            const message = {
                type: 'world_state_agent',
                action: 'determine_avatar',
                character: ctx.character,
                response: ctx.message_content,
                message_ids: [ctx.message_id],
                force_determine: true,
            };
            
            ws.send(JSON.stringify(message));
        },

        /**
         * Handle "Generate new avatar" menu option
         */
        handleGenerateNewAvatar() {
            // Close the menu
            this.assetMenu.show = false;
            
            const ctx = this.assetMenu.context;
            if (!ctx.character || !ctx.message_content || !ctx.message_id) {
                return;
            }

            // Mark this message as processing
            this.processingAssetMessageIds.add(ctx.message_id);

            const ws = this.getWebsocket();
            const message = {
                type: 'world_state_agent',
                action: 'determine_avatar',
                character: ctx.character,
                response: ctx.message_content,
                message_ids: [ctx.message_id],
                force_regenerate: true,
            };
            
            ws.send(JSON.stringify(message));
        },

        openAssetSelectDialog(assetType) {
            const cfg = ASSET_SELECT_TYPES[assetType];
            if (!cfg) {
                return;
            }

            const ctx = this.assetMenu.context;
            if (!ctx?.message_id) {
                return;
            }
            if (cfg.requiresCharacter && !ctx.character) {
                return;
            }

            const dialog = this[cfg.dialogKey];
            if (!dialog) {
                return;
            }

            const assetIds = cfg.getAssetIds(this, ctx) || [];

            // Populate dialog state
            dialog.messageId = ctx.message_id;
            if (cfg.requiresCharacter) {
                dialog.characterName = ctx.character;
            }
            dialog.assetIds = assetIds;
            dialog.selectedAssetId = ctx.asset_id || (assetIds.length > 0 ? assetIds[0] : null);

            // Load base64 for items already in cache
            const base64ById = {};
            assetIds.forEach(assetId => {
                const cached = this.assetCache[assetId];
                if (cached?.base64) {
                    base64ById[assetId] = cached.base64;
                }
            });
            dialog.base64ById = base64ById;

            // Request any missing assets
            const missingIds = assetIds.filter(id => !this.assetCache[id]);
            if (missingIds.length > 0) {
                this.requestSceneAssets(missingIds);
            }

            dialog.show = true;
        },

        confirmAssetSelection(assetType) {
            const cfg = ASSET_SELECT_TYPES[assetType];
            if (!cfg) {
                return;
            }
            const dialog = this[cfg.dialogKey];
            if (!dialog) {
                return;
            }

            const assetId = dialog.selectedAssetId;
            const messageId = dialog.messageId;
            if (!assetId || !messageId) {
                return;
            }
            if (cfg.requiresCharacter && !dialog.characterName) {
                return;
            }

            const ws = this.getWebsocket();
            ws.send(JSON.stringify(cfg.buildUpdateMessage(dialog)));

            this.closeAssetSelectDialog(assetType);
        },

        closeAssetSelectDialog(assetType) {
            const cfg = ASSET_SELECT_TYPES[assetType];
            if (!cfg) {
                return;
            }
            const dialog = this[cfg.dialogKey];
            if (!dialog) {
                return;
            }
            cfg.reset(dialog);
        },

        sendRevisualizeAsset({ assetId, messageId, instructions = null, deleteOld = false }) {
            if (!assetId || !messageId) {
                return;
            }

            // Mark this message as processing
            this.processingAssetMessageIds.add(messageId);

            const ws = this.getWebsocket();
            const message = {
                type: 'visual',
                action: 'revisualize',
                asset_id: assetId,
                asset_allow_override: true,
                asset_allow_auto_attach: true,
            };

            if (deleteOld) {
                message.asset_delete_old = true;
            }

            if (instructions) {
                message.instructions = instructions;
            }

            ws.send(JSON.stringify(message));
        },

        openRevisualizeInstructionsDialog({ deleteOld = false } = {}) {
            // Close the menu
            this.assetMenu.show = false;

            const ctx = this.assetMenu.context;
            if (!ctx.asset_id || !ctx.message_id) {
                return;
            }

            // Open the instructions dialog
            if (this.$refs.requestRegenerateInstructions) {
                this.$refs.requestRegenerateInstructions.openDialog({
                    asset_id: ctx.asset_id,
                    message_id: ctx.message_id,
                    deleteOld: deleteOld,
                });
            }
        },

        /**
         * Handle "Select portrait" menu option
         */
        handleOpenAvatarSelect() {
            // Close the menu
            this.assetMenu.show = false;
            
            this.openAssetSelectDialog('avatar');
        },

        /**
         * Handle "Regenerate Illustration" menu option for card and scene_illustration
         */
        handleRegenerateIllustration() {
            // Close the menu
            this.assetMenu.show = false;
            
            const ctx = this.assetMenu.context;
            if (!ctx.asset_id || !ctx.message_id) {
                return;
            }
            this.sendRevisualizeAsset({
                assetId: ctx.asset_id,
                messageId: ctx.message_id,
                deleteOld: false,
            });
        },

        /**
         * Handle "Delete and Regenerate" menu option for card and scene_illustration
         */
        handleRegenerateAndDeleteIllustration() {
            // Close the menu
            this.assetMenu.show = false;
            
            const ctx = this.assetMenu.context;
            if (!ctx.asset_id || !ctx.message_id) {
                return;
            }
            this.sendRevisualizeAsset({
                assetId: ctx.asset_id,
                messageId: ctx.message_id,
                deleteOld: true,
            });
        },

        /**
         * Handle "Regenerate Illustration" with custom instructions (Ctrl+click)
         */
        handleOpenRegenerateAssetDialog() {
            this.openRevisualizeInstructionsDialog({ deleteOld: false });
        },

        /**
         * Handle "Delete and Regenerate" with custom instructions (Ctrl+click)
         */
        handleOpenRegenerateAndDeleteAssetDialog() {
            this.openRevisualizeInstructionsDialog({ deleteOld: true });
        },

        /**
         * Handle asset regeneration with custom instructions from dialog
         */
        handleRegenerateAssetWithInstructions(instructions, params) {
            if (!params || !params.asset_id || !params.message_id) {
                return;
            }
            this.sendRevisualizeAsset({
                assetId: params.asset_id,
                messageId: params.message_id,
                instructions: instructions,
                deleteOld: !!params.deleteOld,
            });
        },

        /**
         * Confirm avatar selection
         */
        confirmAvatarSelection() {
            this.confirmAssetSelection('avatar');
        },

        /**
         * Close avatar select dialog
         */
        closeAvatarSelectDialog() {
            this.closeAssetSelectDialog('avatar');
        },

        /**
         * Handle "Select illustration" menu option
         */
        handleOpenIllustrationSelect() {
            // Close the menu
            this.assetMenu.show = false;
            
            this.openAssetSelectDialog('scene_illustration');
        },

        /**
         * Confirm illustration selection
         */
        confirmIllustrationSelection() {
            this.confirmAssetSelection('scene_illustration');
        },

        /**
         * Close illustration select dialog
         */
        closeIllustrationSelectDialog() {
            this.closeAssetSelectDialog('scene_illustration');
        },

        /**
         * Handle "Select card" menu option
         */
        handleOpenCardSelect() {
            // Close the menu
            this.assetMenu.show = false;
            
            this.openAssetSelectDialog('card');
        },

        /**
         * Confirm card selection
         */
        confirmCardSelection() {
            this.confirmAssetSelection('card');
        },

        /**
         * Close card select dialog
         */
        closeCardSelectDialog() {
            this.closeAssetSelectDialog('card');
        },

        /**
         * Handle "Clear Image" menu option
         */
        handleClearImage() {
            // Close the menu
            this.assetMenu.show = false;
            
            const ctx = this.assetMenu.context;
            if (!ctx.message_id) {
                return;
            }

            // Mark this message as processing
            this.processingAssetMessageIds.add(ctx.message_id);

            const ws = this.getWebsocket();
            const message = {
                type: 'scene_assets',
                action: 'clear_message_asset',
                message_id: ctx.message_id,
            };
            
            ws.send(JSON.stringify(message));
        },

        /**
         * Handle "Delete Image" menu option
         */
        handleDeleteImage() {
            // Close the menu
            this.assetMenu.show = false;
            
            const ctx = this.assetMenu.context;
            if (!ctx.asset_id) {
                return;
            }

            // Show confirmation dialog
            this.$refs.deleteImageConfirm.initiateAction({
                asset_id: ctx.asset_id,
                message_id: ctx.message_id,
            });
        },

        /**
         * Confirm and execute image deletion
         */
        confirmDeleteImage(params) {
            if (!params || !params.asset_id) {
                return;
            }

            const ws = this.getWebsocket();
            const message = {
                type: 'scene_assets',
                action: 'delete',
                asset_id: params.asset_id,
            };
            
            ws.send(JSON.stringify(message));
        },

        handleMessage(data) {
            // Handle asset-related messages centrally (scene_asset, message_asset_update)
            this.handleAssetMessages(data);

            var i;

            // UX element passthrough messages (may not include data.message)
            if (data.type === 'ux') {
                try {
                    const payload = data.data || {};
                    if (payload.action === 'present' && payload.element) {
                        const el = payload.element;
                        const id = el.id || data.id || `ux_${Date.now()}`;
                        this.messages.push({
                            id: id,
                            type: 'ux',
                            element: el,
                        });
                        // Track UX interaction start — only for blocking elements.
                        // Non-blocking (fire-and-forget) elements must not lock scene input.
                        if (this.beginUxInteraction && el.blocking !== false) {
                            this.beginUxInteraction(id);
                        }
                        return;
                    }
                    if (payload.action === 'close') {
                        const uxId = payload.ux_id || payload.id || data.id;
                        this.closeUxElement(uxId);
                        return;
                    }
                } catch (e) {
                    console.warn('ux message handling failed', e, data);
                    return;
                }
            }

            if (data.type == "clear_screen") {
                this.messages = [];
                this.lastEffectiveAssetIdByScope = {};
                this.assetCache = {};
                this.processingAssetMessageIds.clear();
                this.visualizingMessageIds.clear();
                // Clear UX interaction tracking
                if (this.clearUxInteractions) {
                    this.clearUxInteractions();
                }
            }

            if (data.type == "remove_message") {

                // if the last message is a player_choice message
                // and the second to last message is the message to remove
                // also remove the player_choice message

                if (this.messages.length > 1 && this.messages[this.messages.length - 1].type === 'player_choice' && this.messages[this.messages.length - 2].id === data.id) {
                    this.messages.pop();
                }

                // find message where type == "character" and id == data.id
                // remove that message from the array
                let newMessages = [];
                for (i = 0; i < this.messages.length; i++) {
                    if (this.messages[i].id != data.id) {
                        newMessages.push(this.messages[i]);
                    }
                }
                this.messages = newMessages;

                return
            }

            if (data.type == "regenerate_failed") {
                // In-place regenerate failed: clear the per-slot
                // `regenerating` flag so the pager stops spinning. The
                // message itself was never mutated, so there is nothing
                // else to do.
                const idx = this.revisionFindSlotIndex(data.id);
                if (idx >= 0) {
                    this.messages[idx].regenerating = false;
                }
                return;
            }

            // Catch-all for the assistant router's `regenerate_failed`
            // action: fires for guard-failures (e.g. inactive character)
            // and any exception that escaped `regenerate()` before its
            // own top-level `regenerate_failed` emit. We don't know
            // which slot was targeted at click time, so clear the flag
            // on every revision-supporting message.
            if (data.type === 'assistant' && data.action === 'regenerate_failed') {
                for (let j = 0; j < this.messages.length; j++) {
                    if (this.messages[j].regenerating) {
                        this.messages[j].regenerating = false;
                    }
                }
                // Don't return — other components rely on the assistant
                // event for their own input-busy bookkeeping.
            }

            // The editor router posts an `operation_done` envelope when a
            // revision finishes via the no-op, failure, or cancel path (the
            // happy path clears below via `message_edited` reason='revision').
            // The envelope carries no id, so clear only the tracked pending
            // slot — clearing all flagged slots would stop a concurrent
            // in-place regenerate's spinner. Don't return — other components
            // consume the envelope for their own busy bookkeeping.
            if (data.type === 'editor' && data.action === 'operation_done') {
                this.clearRevisionPending();
            }

            if (data.type == "system" && data.id == "scene.looading") {
                // scene started loaded, clear messages
                this.messages = [];
                this.lastEffectiveAssetIdByScope = {};
                this.assetCache = {};
                this.processingAssetMessageIds.clear();
                this.visualizingMessageIds.clear();
                return;
            }

            if (data.type == "message_edited") {

                // find the message by id and update the text + mirror
                // the authoritative revision stack from the wire.
                for (i = 0; i < this.messages.length; i++) {
                    if (this.messages[i].id == data.id) {
                        const msg = this.messages[i];
                        msg.text = this.revisionStripForDisplay(
                            msg.type,
                            msg.character,
                            data.message,
                        );
                        this.revisionApplyServerState(
                            msg,
                            data.versions,
                            data.active_version,
                        );
                        // Any in-flight spinner (manual editor revision or
                        // in-place regenerate) clears on the echo — the
                        // server has now produced the new canonical.
                        this.clearRevisionPending();
                        msg.regenerating = false;
                        break;
                    }
                }

                return
            }

            // `world_state` fires twice per request_update cycle: once with
            // status="requested" carrying the *previous* state (drives the
            // sidebar spinner), then with the default status carrying the
            // fresh snapshot. We only care about the fresh one.
            if (data.type === 'world_state' && data.status !== 'requested' && data.data) {
                this.rebuildWorldStateEntities(data.data);
                return;
            }

            if (data.type === 'world_state_manager' && data.action === 'character_color_updated') {
                // find the message by id and update the color
                for (i = 0; i < this.messages.length; i++) {
                    let message = this.messages[i];
                    if (message.character == data.data.name && message.type == 'character') {
                        message.color = data.data.color;
                        break;
                    }
                }
                return;
            }
            
            if (data.message) {

                if(data.flags && data.flags & MESSAGE_FLAGS.HIDDEN) {
                    return;
                }

                // if the previous message was a player choice message, remove it
                if (this.messageTypeIsSceneMessage(data.type)) {
                    if(this.messages.length > 0 && this.messages[this.messages.length - 1].type === 'player_choice') {
                        this.messages.pop();
                    }
                }

                if (data.type === 'character') {
                    const parts = data.message.split(':');
                    const character = parts.shift();
                    const text = parts.join(':');
                    const characterName = character.trim();

                    // Determine if this message has a non-avatar asset type attached
                    const hasNonAvatarAsset = data.asset_type && data.asset_type !== 'avatar';

                    let finalAssetId = data.asset_id || null;
                    let finalAssetType = data.asset_type || null;
                    let disableAvatarFallback = false;

                    if (hasNonAvatarAsset) {
                        // Non-avatar asset (e.g., scene_illustration, card) - don't apply avatar cadence
                        // Just pass through the asset as-is
                        finalAssetId = data.asset_id;
                        finalAssetType = data.asset_type;
                        disableAvatarFallback = false;
                    } else {
                        // Avatar or no asset - apply cadence logic for avatars
                        const cadenceResult = this.applyAssetCadence('avatar', characterName, data.asset_id);
                        finalAssetId = cadenceResult.effectiveAssetId;
                        finalAssetType = cadenceResult.shouldShow ? 'avatar' : null;
                        disableAvatarFallback = cadenceResult.disableFallback;
                    }

                    const charMsg = {
                        id: data.id,
                        type: data.type,
                        character: characterName,
                        text: text.trim(),
                        color: data.color,
                        // Store raw fields for reprocessing when cadence changes
                        raw_asset_id: data.asset_id || null,
                        raw_asset_type: data.asset_type || null,
                        // Computed render fields (affected by cadence)
                        asset_id: finalAssetId,
                        asset_type: finalAssetType,
                        disable_avatar_fallback: disableAvatarFallback,
                        rev: data.rev || 0
                    };
                    this.revisionApplyServerState(charMsg, data.versions, data.active_version);
                    this.messages.push(charMsg);
                } else if (data.type === 'director') {
                    this.messages.push(
                        {
                            id: data.id,
                            type: data.type,
                            character: data.character,
                            text: data.message,
                            direction_mode: data.direction_mode,
                            action: data.action,
                            subtype: data.subtype,
                            rev: data.rev || 0
                        }
                    );
                } else if (data.type === 'context_investigation') {
                    const ctxMsg = {
                        id: data.id,
                        type: data.type,
                        sub_type: data.sub_type,
                        source_arguments: data.source_arguments,
                        source_agent: data.source_agent,
                        source_function: data.source_function,
                        text: data.message,
                        asset_id: data.asset_id,
                        asset_type: data.asset_type,
                    };
                    this.revisionApplyServerState(ctxMsg, data.versions, data.active_version);
                    this.messages.push(ctxMsg);
                } else if (data.type === 'narrator') {
                    const narratorMsg = {
                        id: data.id,
                        type: data.type,
                        text: data.message,
                        character: data.character,
                        meta: data.meta,
                        rev: data.rev || 0,
                        asset_id: data.asset_id || null,
                        asset_type: data.asset_type || null,
                    };
                    this.revisionApplyServerState(narratorMsg, data.versions, data.active_version);
                    this.messages.push(narratorMsg);
                } else if (data.type === 'player_choice') {
                    console.log('player_choice', data);
                    this.messages.push({ id: data.id, type: data.type, data: data.data });
                } else if (this.messageTypeIsSceneMessage(data.type)) {
                    console.log('scene message', data);
                    const genericMsg = {
                        id: data.id,
                        type: data.type,
                        text: data.message,
                        color: data.color,
                        character: data.character,
                        status: data.status,
                        ts: data.ts,
                        meta: data.meta,
                        rev: data.rev || 0,
                        asset_id: data.asset_id || null,
                        asset_type: data.asset_type || null,
                    };
                    this.revisionApplyServerState(genericMsg, data.versions, data.active_version);
                    this.messages.push(genericMsg);
                } else if (data.type === 'status' && data.data && data.data.as_scene_message === true) {

                    // status message can only exist once, remove the most recent one (if within the last 100 messages)
                    // by walking the array backwards then removing the first one found
                    // then add the new status message
                    let max = 100;
                    let iter = 0;
                    for (i = this.messages.length - 1; i >= 0; i--) {
                        if (this.messages[i].type == 'status') {
                            this.messages.splice(i, 1);
                            break;
                        }
                        iter++;
                        if(iter > max) {
                            break;
                        }
                    }

                    this.messages.push({
                         id: data.id, 
                         type: data.type,
                         text: data.message, 
                         status: data.status, 
                         ts: data.ts,
                    });
                }
                
            }


        }
    },
    watch: {
        // Watch for changes to message asset cadence config only (not all appearance changes)
        messageAssetsConfig: {
            handler: function(newVal) {
                if (!newVal || this.messages.length === 0) {
                    return;
                }
                // Debounce to avoid excessive reapplication during rapid config changes
                if (this._reapplyDebounceTimer) {
                    clearTimeout(this._reapplyDebounceTimer);
                }
                this._reapplyDebounceTimer = setTimeout(() => {
                    this.reapplyMessageAssetCadence();
                    this._reapplyDebounceTimer = null;
                }, 50);
            },
            deep: true,
        }
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    beforeUnmount() {
        // Clean up debounce timer if component is destroyed
        if (this._reapplyDebounceTimer) {
            clearTimeout(this._reapplyDebounceTimer);
            this._reapplyDebounceTimer = null;
        }
    },
}

</script>

<style scoped>
.message-container {
    overflow-y: auto;
}

.message-wrapper {
    position: relative;
}

.message {
    white-space: pre-wrap;
}

.message.system {
    color: #FFA726;
}

.message.narrator {
    color: #26A69A;
}

.message.character {
    color: #E0E0E0;
}

.character-message {
    display: flex;
    flex-direction: row;
}

.character-name {
    font-weight: bold;
    margin-right: 10px;
}

.character-avatar {
    height: 50px;
    margin-top: 10px;
}

.hotbuttons-section {
    display: flex;
    justify-content: flex-start;
    margin-bottom: 10px;
}

.hotbuttons-section-1,
.hotbuttons-section-2,
.hotbuttons-section-3 {
    display: flex;
    align-items: center;
    margin-right: 20px;
}

.choice-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}

/* Inline entity highlights rendered by SceneTextParser inside v-html'd
   message bodies. Subtle dotted underline + hover affordance signals
   "this message has examinables; others won't have any". The text color
   is set inline from appearance.scene.entities; the underline
   inherits via currentColor so it always matches the resolved color. */
.message-container :deep(.scene-entity) {
    cursor: pointer;
    text-decoration: underline dotted currentColor;
    text-underline-offset: 3px;
    transition: background-color 0.15s ease;
    border-radius: 2px;
}

.message-container :deep(.scene-entity:hover) {
    background-color: rgba(var(--v-theme-highlight5), 0.15);
}

</style>