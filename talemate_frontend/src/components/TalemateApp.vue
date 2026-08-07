<template>
  <v-app>

    <!-- system bar -->
    <v-system-bar>
      <v-icon icon="mdi-network-outline"></v-icon>

      <span v-for="name in sortedClientNames" :key="name">
        <v-fade-transition>
          <v-chip v-if="clientStatus[name].recentlyActive" label size="x-small" class="mr-1" variant="text">
            <template v-slot:prepend>
              <v-progress-circular v-if="clientStatus[name].busy" indeterminate="disable-shrink" :color="(clientStatus[name].busy_bg ? 'secondary' : 'primary')" size="11"></v-progress-circular>
              <v-icon v-else color="muted" size="11">mdi-circle-outline</v-icon>
            </template>
            <span class="ml-1">{{ clientStatus[name].label }}</span>
          </v-chip>
        </v-fade-transition>
      </span>

      <v-icon icon="mdi-transit-connection-variant" class="mr-1"></v-icon>

      <span v-for="name in sortedAgentNames" :key="name">
        <v-fade-transition>
          <v-chip v-if="agentStatus[name].recentlyActive" label size="x-small" class="mr-1" variant="text">
            <template v-slot:prepend>
              <v-progress-circular v-if="agentStatus[name].busy" indeterminate="disable-shrink" :color="(agentStatus[name].busy_bg ? 'secondary' : 'primary')" size="11"></v-progress-circular>
              <v-icon v-else color="muted" size="11">mdi-circle-outline</v-icon>
            </template>
            <span class="ml-1">{{ agentStatus[name].label }}</span>
          </v-chip>
        </v-fade-transition>
      </span>

      <v-divider vertical class="ml-1"></v-divider>
      
      <v-chip variant="text" prepend-icon="mdi-progress-helper" v-if="connecting" color="info" size="x-small" class="mr-1" label>connecting</v-chip>
      <v-chip variant="text" prepend-icon="mdi-checkbox-blank-circle" v-else-if="connected" color="success" size="x-small" class="mr-1" label>connected</v-chip>
      <v-chip variant="text" prepend-icon="mdi-progress-close" v-else color="error" size="x-small" class="mr-1" label>disconnected</v-chip>


      <v-divider class="mr-1" vertical></v-divider>
      <v-spacer></v-spacer>
      <AudioQueue ref="audioQueue" @message-audio-played="onMessageAudioPlayed" />
      <v-divider class="ml-2 mr-2" vertical></v-divider>
      <span v-if="version !== null" class="text-grey text-caption">v{{ version }}</span>
      <span v-if="!ready">
        <v-icon icon="mdi-application-cog"></v-icon>
        <span class="ml-1">Configuration required</span>
      </span>

    </v-system-bar>

    <!-- app bar -->
    <v-app-bar app density="compact">
      <v-app-bar-nav-icon v-if="tab !== 'home'" size="small" @click="toggleNavigation('game')">
        <v-tooltip activator="parent" location="top">Toggle sidebar</v-tooltip>
        <v-icon v-if="sceneDrawer">mdi-arrow-collapse-left</v-icon>
        <v-icon v-else>mdi-arrow-collapse-right</v-icon>
      </v-app-bar-nav-icon>

      <v-app-bar-nav-icon v-if="sceneActive && scene.environment === 'scene'" @click="setEnvCreative(); tab = 'main'" color="highlight6" icon>
        <v-tooltip activator="parent" location="top">Change to node editor</v-tooltip>
        <v-icon>mdi-chart-timeline-variant-shimmer</v-icon>
      </v-app-bar-nav-icon>
      <v-app-bar-nav-icon v-else-if="sceneActive && scene.environment === 'creative'" @click="requestNodeEditorExit" color="highlight4" icon>
        <v-tooltip activator="parent" location="top">Exit node editor</v-tooltip>
        <v-icon>mdi-exit-to-app</v-icon>
      </v-app-bar-nav-icon>
      
      <v-tabs v-model="tab" color="primary">
        <v-tab v-for="tab in availableTabs" :key="tab" :value="tab.value" @click.stop="onTabClick(tab)">
          <v-icon class="mr-1">{{ tab.icon() }}</v-icon>
          {{ tab.title() }}
          <span v-if="tab.alert && tab.alert()" class="ml-1 d-inline-flex">
            <v-tooltip v-if="tab.alertTooltip" activator="parent" location="top">{{ tab.alertTooltip() }}</v-tooltip>
            <v-icon size="x-small" color="warning">mdi-alert</v-icon>
          </span>
        </v-tab>
      </v-tabs>
  
      <v-spacer></v-spacer>

      <DirectorConsoleWidget :scene-active="sceneActive" @open-director-console="toggleNavigation('directorConsole')" />

      <VoiceLibrary :scene-active="sceneActive" :scene="scene" :app-busy="busy" :app-ready="ready" v-if="agentStatus.tts?.available"/>

      <VisualLibrary ref="visualLibrary" :scene-active="sceneActive" :scene="scene" :app-busy="busy" :app-ready="ready" :agent-status="agentStatus" :world-state-templates="worldStateTemplates"/>


      <v-tooltip text="Help" location="top">
        <template v-slot:activator="{ props }">
          <v-app-bar-nav-icon @click="toggleNavigation('help')" v-bind="props"><v-icon>mdi-help-circle-outline</v-icon></v-app-bar-nav-icon>
        </template>
      </v-tooltip>

      <v-tooltip text="Debug Tools" location="top">
        <template v-slot:activator="{ props }">
          <v-app-bar-nav-icon @click="toggleNavigation('debug')" v-bind="props"><v-icon>mdi-bug</v-icon></v-app-bar-nav-icon>
        </template>
      </v-tooltip>

      <v-tooltip text="Settings" location="top">
        <template v-slot:activator="{ props }">
          <v-app-bar-nav-icon @click="openAppConfig()" v-bind="props"><v-icon>mdi-cog</v-icon></v-app-bar-nav-icon>
        </template>
      </v-tooltip>

      <v-tooltip text="Clients / Agents" location="top">
        <template v-slot:activator="{ props }">
          <v-app-bar-nav-icon @click="toggleNavigation('settings')" v-if="!ready" v-bind="props" color="red-darken-1"><v-icon>mdi-application-cog</v-icon></v-app-bar-nav-icon>
          <v-app-bar-nav-icon @click="toggleNavigation('settings')" v-else v-bind="props"><v-icon>mdi-application-cog</v-icon></v-app-bar-nav-icon>
        </template>
      </v-tooltip>

    </v-app-bar>

    <!-- removed creative mode toolbar; controls moved into NodeEditor toolbar -->

    <v-main style="height: 100%; display: flex; flex-direction: column;">

      <!-- left side navigation drawer -->
      <v-navigation-drawer :model-value="sceneDrawer && tab !== 'home'" @update:model-value="sceneDrawer = $event" app :width="leftDrawerWidth">
        <v-alert v-if="!connected" type="error" variant="tonal">
          Not connected to Talemate backend
          <p class="text-body-2" color="white">
            Make sure the backend process is running.
          </p>
        </v-alert>
        <v-alert type="warning" variant="tonal" v-if="!ready && connected">There are some outstanding configuration issues, please ensure that all enabled agents are configured correctly.</v-alert>
        <v-tabs-window v-model="tab">
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="main">
            <CoverImage v-if="sceneActive" ref="coverImage" type="scene" :target="scene" />
            <WorldState v-if="sceneActive" ref="worldState" :busy="busy" @passive-characters="(characters) => { passiveCharacters = characters }"  @open-world-state-manager="onOpenWorldStateManager"/>
          </v-tabs-window-item>
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="world">
            <WorldStateManagerMenu v-if="sceneActive"
            ref="worldStateManagerMenu" 
            :scene="scene"
            :worldStateTemplates="worldStateTemplates"
            :app-busy="busy"
            :app-ready="ready"
            @world-state-manager-navigate="onOpenWorldStateManager" 
            />
          </v-tabs-window-item>
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="package_manager">
            <PackageManagerMenu v-if="sceneActive"
            ref="packageManagerMenu" 
            :scene="scene"
            :app-busy="busy"
            :app-ready="ready"
            />
          </v-tabs-window-item>
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="templates">
            <TemplatesMenu
            ref="templatesMenu"
            :templates="worldStateTemplates"
            :selected-groups="templatesSelectedGroups"
            :selected="templatesSelected"
            @navigate-template="onNavigateTemplate"
            @update:selectedGroups="templatesSelectedGroups = $event"
            @update:selected="templatesSelected = $event"
            />
          </v-tabs-window-item>
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="prompts">
            <PromptsMenu
              ref="promptsMenu"
              :prompts="promptsViewPrompts"
              :recent-templates="recentTemplates"
              v-model:active-tab="promptsMainTab"
              @navigate-template="onNavigatePromptTemplate"
              @open-prompt="onOpenPrompt"
              @clear-prompts="onClearPrompts"
            />
          </v-tabs-window-item>
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="settings">
            <AppSettingsMenu :page="appSettingsPage" @navigate="onAppSettingsNavigate" />
          </v-tabs-window-item>
        </v-tabs-window>

      </v-navigation-drawer>
      <!-- right side navigation drawer -->
      <v-navigation-drawer v-model="drawer" app location="right" width="350" disable-resize-watcher>
        <v-alert v-if="!connected" type="error" variant="tonal">
          Not connected to Talemate backend
          <p class="text-body-2" color="white">
            Make sure the backend process is running.
          </p>
        </v-alert>
        <v-alert v-else-if="!ready" type="warning" variant="tonal">
          There are some outstanding configuration issues, please ensure that all enabled agents are configured correctly.
        </v-alert>

        <v-list>
          <AIClient ref="aiClient" @save="saveClients" @error="uxErrorHandler" @clients-updated="saveClients" @client-assigned="saveAgents" @open-app-config="openAppConfig" :immutable-config="appConfig" :app-config="appConfig"></AIClient>
          <v-divider></v-divider>
          <AIAgent ref="aiAgent" @agents-updated="saveAgents" :agentState="agentState" :templates="worldStateTemplates" :app-config="appConfig" :scene="scene"></AIAgent>
          <!-- More sections can be added here -->
        </v-list>
      </v-navigation-drawer>

      <!-- director console navigation drawer -->
      <v-navigation-drawer v-model="directorConsoleDrawer" app location="right" :width="rightToolsDrawerWidth" disable-resize-watcher>
        <DirectorConsole :scene="scene" v-if="sceneActive" :app-busy="busy" :app-ready="ready" :open="directorConsoleDrawer" />
      </v-navigation-drawer>

      <!-- help chat navigation drawer -->
      <v-navigation-drawer v-model="helpDrawer" app location="right" :width="rightToolsDrawerWidth" disable-resize-watcher>
        <HelpChat v-if="helpDrawer && connected" :scene-active="sceneActive" :agent-status="agentStatus" :ux-snapshot="buildUxSnapshot" />
      </v-navigation-drawer>

      <!-- debug tools navigation drawer -->
      <v-navigation-drawer v-model="debugDrawer" app location="right" width="400" disable-resize-watcher>
        <v-list>
          <v-list-subheader class="text-uppercase"><v-icon>mdi-bug</v-icon> Debug Tools</v-list-subheader>
          <DebugTools ref="debugTools" :scene="scene" :prompts="promptsViewPrompts" :app-config="appConfig" @clear-prompts="clearPrompts"></DebugTools>
        </v-list>
      </v-navigation-drawer>

      <v-container :class="(sceneActive ? '' : 'backdrop')" fluid style="height: 100%;">

        <v-tabs-window v-model="tab" style="height: 100%;">
          <!-- HOME -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="home">
            <SceneLanding
            ref="sceneLanding"
            @request-scene-load="(path) => {  resetViews(); $refs.sceneLanding.loadJsonSceneFromPath(path); }"
            @loading="sceneStartedLoading"
            @open-director="openDirectorWithChat"
            :connected="connected"
            :scene-loading-available="ready && connected"
            :scene-is-loading="loading"
            :visible="tab === 'home'"
            :world-state-templates="worldStateTemplates"
            :config="appConfig" />
          </v-tabs-window-item>
          <!-- SCENE -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="main" style="height: 100%;">
            <v-row no-gutters class="position-relative">
              <v-col ref="nodeEditorContainer" v-resize="onNodeEditorContainerResize" :xl="creativeMode ? (showSceneView ? 8 : 12) : 0" :cols="creativeMode ? (showSceneView ? 6 : 12) : 0" :class="{ 'd-none': !creativeMode }" class="position-relative">
                  <NodeEditor
                    :scene="scene"
                    :busy="busy"
                    :app-config="appConfig"
                    :templates="worldStateTemplates"
                    :is-visible="creativeMode"
                    :scene-view-visible="showSceneView"
                    @toggle-scene-view="toggleSceneView"
                    ref="nodeEditor"
                    v-if="sceneActive && scene.environment === 'creative'"
                  >
                  </NodeEditor>  
              </v-col>
              <v-col :cols="creativeMode ? (showSceneView ? 6 : 0) : 12"  :xl="creativeMode ? (showSceneView ? 4 : 12) : 12" :class="{ 'pl-2': true, 'd-none': creativeMode && !showSceneView, 'scene-backdrop-active': !!sceneBackdropSrc }" :style="sceneBackdropStyle">
                <div class="scene-column" style="display: flex; flex-direction: column; height: 100%">

                  <div class="scene-container">

                    <div v-if="sceneActive && scene.environment === 'creative' && !scene.data.intro">
                      <v-alert color="muted" class="mb-2" variant="text">
                        <v-alert-title>New Scene</v-alert-title>
                        You're editing a new scene. Select the <v-btn @click="onOpenWorldStateManager('scene')" variant="text" size="small" color="primary" prepend-icon="mdi-earth-box">World Editor</v-btn> to add characters and scene details. You are currently operating in the creative environment. Once you have added at least one player character you may switch back and forth between creative and gameplay mode at any point using the <v-icon color="primary" size="small">mdi-gamepad-square</v-icon> button at the bottom.
                        <p class="mt-4">
                          You can still use the world editor while in gameplay mode as well.
                        </p>
                      </v-alert>
                    </div>

                    <div v-show="showSceneView" class="scene-view">
                      <SceneMessages
                        ref="sceneMessages"
                        :appearance-config="effectiveAppearanceConfig"
                        :ux-locked="uxLocked"
                        :app-busy="busy"
                        :agent-status="agentStatus"
                        :audio-played-for-message-id="audioPlayedForMessageId"
                        :scene="scene"
                        @cancel-audio-queue="onCancelAudioQueue"
                        @configure-entity-highlights="onConfigureEntityHighlights"
                        @scene-backdrop="sceneBackdropSrc = $event"
                        @scene-backdrop-candidate="sceneBackdropCandidate = $event"
                      />
                    </div>

                    <div ref="sceneToolsContainer" class="scene-controls" :class="{ 'scene-controls--locked': uxInteractionActive }">
                      <AgentActivityBar v-if="appConfig?.game?.general?.show_agent_activity_bar !== false" :agent-status="agentStatus" />
                      <SceneTools 
                        @open-world-state-manager="onOpenWorldStateManager"
                        @open-agent-messages="onOpenAgentMessages"
                        @cancel-audio-queue="onCancelAudioQueue"
                        :messageInput="messageInput"
                        :agent-status="agentStatus"
                        :app-busy="busy"
                        :app-ready="ready"
                        :worldStateTemplates="worldStateTemplates"
                        :playerCharacterName="getPlayerCharacterName()"
                        :passiveCharacters="passiveCharacters"
                        :inactiveCharacters="inactiveCharacters"
                        :scene="scene"
                        :activeCharacters="activeCharacters"
                        :visual-agent-ready="visualAgentReady"
                        :scene-backdrop-candidate="sceneBackdropCandidate"
                        :audioPlayedForMessageId="audioPlayedForMessageId" />
                      <SceneMessageInput
                        ref="sceneMessageInput"
                        v-model="messageInput"
                        v-model:act-as="actAs"
                        :busy="busy"
                        :ready="ready"
                        :ux-interaction-active="uxInteractionActive"
                        :input-disabled="isInputDisabled()"
                        :waiting-for-input="waitingForInput"
                        :input-request-info="inputRequestInfo"
                        :scene-active="sceneActive"
                        :scene-environment="scene.environment"
                        :character-colors="scene.data?.character_colors"
                        :player-character-name="getPlayerCharacterName()"
                        :active-characters="activeCharacters"
                        :direction-available="directionAvailable"
                        @send="onInputSend"
                        @autocomplete-start="onAutocompleteStart"
                        @autocomplete-end="onAutocompleteEnd" />
                    </div>
                  </div>

                </div>
    
                
              </v-col>
            </v-row>




          </v-tabs-window-item>
          <!-- WORLD -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="world">
            <WorldStateManager 
            :world-state-templates="worldStateTemplates"
            :scene="scene"
            :agent-status="agentStatus"
            :app-config="appConfig"
            :app-busy="busy"
            :app-ready="ready"
            :visible="tab === 'world'"
            :visual-agent-ready="visualAgentReady"
            :image-edit-available="imageEditAvailable"
            :image-create-available="imageCreateAvailable"
            @navigate-r="onWorldStateManagerNavigateR"
            @selected-character="onWorldStateManagerSelectedCharacter"
            ref="worldStateManager" />
          </v-tabs-window-item>
          <!-- MODULES -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="package_manager">
            <PackageManager :visible="tab === 'package_manager'" :scene="scene" :app-busy="busy" :app-ready="ready" />
          </v-tabs-window-item>
          <!-- TEMPLATES -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="templates">
            <Templates
            :immutable-templates="worldStateTemplates"
            :scene-active="sceneActive"
            ref="templates"
            @selection-changed="onTemplatesSelectionChanged" />
          </v-tabs-window-item>
          <!-- PROMPTS -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="prompts">
            <PromptsView :visible="tab === 'prompts'" :prompts="prompts" :agent-status="agentStatus" :app-config="appConfig" ref="promptsView" v-model:main-tab="promptsMainTab" @clear-prompts="onClearPrompts" />
          </v-tabs-window-item>
          <!-- SETTINGS -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="settings">
            <AppSettings
            ref="appSettings"
            :agent-status="agentStatus"
            :scene-active="sceneActive"
            :client-status="clientStatus"
            :visible="tab === 'settings'"
            @appearance-preview="onAppearancePreview"
            @appearance-preview-clear="onAppearancePreviewClear"
            @page-changed="(page) => appSettingsPage = page"
            @dirty-changed="(dirty) => appSettingsDirty = dirty"
            @save-state-changed="(state) => appSettingsSaveState = state" />
          </v-tabs-window-item>

        </v-tabs-window>

      </v-container>
    </v-main>

    <AgentActionOverrides ref="agentActionOverrides" :app-config="appConfig" :agent-status="agentStatus" />

    <v-dialog v-model="worldEditorUnavailable" max-width="420">
      <v-card>
        <v-card-title>
          <v-icon start color="warning">mdi-earth-box-off</v-icon>
          World editor unavailable
        </v-card-title>
        <v-card-text>
          The world editor requires a loaded scene. Load or create a scene first.
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn color="primary" variant="text" @click="worldEditorUnavailable = false">OK</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <v-dialog v-model="unsavedSettingsPrompt" max-width="480" persistent>
      <v-card>
        <v-card-title>
          <v-icon start color="warning">mdi-content-save-alert-outline</v-icon>
          You have unsaved settings
        </v-card-title>
        <v-card-text>
          You have unsaved changes in Settings. Save them, discard them, or leave them pending and return to Settings later.
          <p v-if="appSettingsSaveState.externalChange" class="text-warning mt-2 text-caption">
            The configuration was changed outside this view while you have unsaved edits — saving overwrites it.
          </p>
        </v-card-text>
        <v-card-actions>
          <v-btn color="delete" variant="text" prepend-icon="mdi-undo" @click="onUnsavedSettingsDiscard">Discard Changes</v-btn>
          <v-spacer></v-spacer>
          <v-btn color="muted" variant="text" @click="onUnsavedSettingsIgnore">Ignore</v-btn>
          <v-btn color="primary" variant="text" prepend-icon="mdi-check-circle-outline" :disabled="!appSettingsSaveState.canSave" @click="onUnsavedSettingsSave">Save</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <v-snackbar v-model="errorNotification" color="red-darken-1" :timeout="3000">
        {{ errorMessage }}
    </v-snackbar>
  </v-app>
  <StatusNotification />
  <RateLimitAlert ref="rateLimitAlert" />
  <AutoRetryAlert ref="autoRetryAlert" />
  <GenerationErrorDialog ref="generationErrorDialog" />
  <SceneTimeline
    ref="sceneTimeline"
    :scene="scene"
    :appearance-config="effectiveAppearanceConfig"
    @load-at-revision="(target) => { resetViews(); $refs.sceneLanding.loadJsonSceneFromPath(target.path, false, target.rev); }"
  />
  <VersionMismatchAlert ref="versionMismatchAlert" />
  <OnboardingWizard
    v-if="connected && appConfig && appConfig.clients"
    :clients="Object.values(appConfig.clients || {})"
    :agents="Object.values(agentStatus || {})"
    @open-client-modal="(preset) => $refs.aiClient.openModal(preset)"
  />
</template>
  
<script>
import AIClient from './AIClient.vue';
import AIAgent from './AIAgent.vue';
import AgentActivityBar from './AgentActivityBar.vue';
import AgentActionOverrides from './AgentActionOverrides.vue';
import SceneLanding from './SceneLanding.vue';
import SceneTools from './SceneTools.vue';
import SceneMessages from './SceneMessages.vue';
import SceneMessageInput from './SceneMessageInput.vue';
import WorldState from './WorldState.vue';
import CoverImage from './CoverImage.vue';
import AppSettings from './AppSettings.vue';
import AppSettingsMenu from './AppSettingsMenu.vue';
import DebugTools from './DebugTools.vue';
import AudioQueue from './AudioQueue.vue';
import StatusNotification from './StatusNotification.vue';
import RateLimitAlert from './RateLimitAlert.vue';
import AutoRetryAlert from './AutoRetryAlert.vue';
import GenerationErrorDialog from './GenerationErrorDialog.vue';
import SceneTimeline from './SceneTimeline.vue';
import VersionMismatchAlert from './VersionMismatchAlert.vue';
import { versionsMatch } from '@/constants/version';
import VisualLibrary from './VisualLibrary.vue';
import VoiceLibrary from './VoiceLibrary.vue';
import WorldStateManager from './WorldStateManager.vue';
import WorldStateManagerMenu from './WorldStateManagerMenu.vue';
import NodeEditor from './NodeEditor.vue';
import DirectorConsole from './DirectorConsole.vue';
import DirectorConsoleWidget from './DirectorConsoleWidget.vue';
import HelpChat from './HelpChat.vue';
import PackageManager from './PackageManager.vue';
import PackageManagerMenu from './PackageManagerMenu.vue';
import Templates from './Templates.vue';
import TemplatesMenu from './TemplatesMenu.vue';
import OnboardingWizard from './OnboardingWizard.vue';
import PromptsView from './prompts/PromptsView.vue';
import PromptsMenu from './prompts/PromptsMenu.vue';
// import debounce
import { debounce } from 'lodash';
import { effectiveActionEnabled } from '@/constants/sceneAgentSettings';
import { isVisualAgentReady, isImageEditAvailable, isImageCreateAvailable } from '@/constants/visual';
import { createSceneAssetsRequester } from './VisualAssetsMixin.js';
import AutocompleteMixin from './AutocompleteMixin.js';

export default {
  components: {
    AIClient,
    AIAgent,
    AgentActivityBar,
    AgentActionOverrides,
    SceneLanding,
    SceneTools,
    SceneMessages,
    SceneMessageInput,
    WorldState,
    CoverImage,
    AppSettings,
    AppSettingsMenu,
    DebugTools,
    AudioQueue,
    StatusNotification,
    VisualLibrary,
    WorldStateManager,
    WorldStateManagerMenu,
    NodeEditor,
    DirectorConsole,
    RateLimitAlert,
    AutoRetryAlert,
    GenerationErrorDialog,
    SceneTimeline,
    VersionMismatchAlert,
    DirectorConsoleWidget,
    HelpChat,
    PackageManager,
    PackageManagerMenu,
    VoiceLibrary,
    Templates,
    TemplatesMenu,
    OnboardingWizard,
    PromptsView,
    PromptsMenu,
  },
  name: 'TalemateApp',
  mixins: [AutocompleteMixin],
  data() {
    return {
      appearancePreview: null, // Preview config while editing settings (null = use saved config)
      // data-url of the scene illustration acting as the scene backdrop
      // (scene.assets.backdrop), reported up by SceneMessages which owns
      // the asset cache
      sceneBackdropSrc: null,
      // asset id of the most recent message-attached background image the
      // scene-tools "Immersive" chip promotes when no backdrop is set
      sceneBackdropCandidate: null,
      tab: 'home',
      tabs: [
        {
          title: () => {
            return this.scene.title || 'Untitled Scenario';
          }, 
          condition: () => { return this.sceneActive },
          icon: () => { return 'mdi-script' },
          click: () => {
            // on next tick, scroll to the bottom of the message list
            this.$nextTick(() => {
              this.$refs.sceneMessageInput?.scrollIntoView(false);
            });
          },
          value: 'main'
        },
        { 
          title: () => { return 'World Editor' },
          condition: () => { return this.sceneActive },
          icon: () => { return 'mdi-earth-box' },
          click: () => { 
            this.$nextTick(() => {
              this.onOpenWorldStateManager();
            });
          },
          value: 'world' 
        },
        {
          title: () => { return 'Mods' },
          condition: () => { return this.sceneActive },
          icon: () => { return 'mdi-package-variant' },
          click: () => {
            this.$nextTick(() => {
              this.onOpenPackageManager();
            });
          },
          value: 'package_manager'
        },
        {
          title: () => { return 'Templates' },
          condition: () => { return true },
          icon: () => { return 'mdi-cube-scan' },
          click: () => {
            // Templates tab clicked
          },
          value: 'templates'
        },
        {
          title: () => { return 'Prompts' },
          condition: () => { return true },
          icon: () => { return 'mdi-file-code-outline' },
          alert: () => { return this.promptsOutdatedCount > 0 },
          click: () => {
            // Prompts tab clicked
          },
          value: 'prompts'
        },
        {
          title: () => { return 'Settings' },
          condition: () => { return true },
          icon: () => { return 'mdi-cog' },
          alert: () => { return this.appSettingsDirty },
          alertTooltip: () => { return 'You have unsaved changes in Settings' },
          click: () => {
            // Settings tab clicked
          },
          value: 'settings'
        },
        {
          title: () => { return 'Home' },
          condition: () => { return true },
          icon: () => { return 'mdi-home' },
          click: () => {
            // on next tick, scroll to the top
            this.$nextTick(() => {
              window.scrollTo(0, 0);
            });
          },
          value: 'home'
        },
      ],
      version: null,
      loading: false,
      favicon: null,
      sceneActive: false,
      drawer: false,
      sceneDrawer: true,
      debugDrawer: false,
      directorConsoleDrawer: false,
      helpDrawer: false,
      worldEditorUnavailable: false,
      websocket: null,
      inputDisabled: false,
      waitingForInput: false,
      inputRequestInfo: null,
      connectTimeout: null,
      connected: false,
      connecting: false,
      reconnect: true,
      errorMessage: null,
      errorNotification: false,
      notificatioonBusy: false,
      ready: false,
      messageInput: '',
      reconnectInterval: 3000,
      passiveCharacters: [],
      inactiveCharacters: [],
      activeCharacters: [],
      messageHandlers: [],
      scene: {},
      actAs: null,
      appConfig: {},
      worldStateTemplates: {},
      // busy status of agents
      agentStatus: {},
      // scene state of agents
      agentState: {},
      clientStatus: {},
      // timestamps for last agent and client updates
      // received from the backend
      lastAgentUpdate: null,
      lastClientUpdate: null,
      busy: false,
      visualBusyTimer: null,
      audioPlayedForMessageId: undefined,
      showSceneView: true,
      templatesSelectedGroups: [],
      templatesSelected: null,
      mainTabScrollPosition: null,
      // Scene assets requester (initialized when websocket is available)
      _sceneAssetsRequester: null,
      // Track active UX interaction IDs (for disabling scene controls during UX interactions)
      activeUxInteractionIds: [],
      // Prompt capture state (moved from PromptsView for always-on capture)
      prompts: [],
      promptTotal: 0,
      maxPrompts: 50,
      // Recent templates (pushed from backend)
      recentTemplates: [],
      // Synced tab state between PromptsMenu and PromptsView
      promptsMainTab: 'prompts',
      // Synced page state between AppSettingsMenu and AppSettings
      appSettingsPage: 'gameplay',
      appSettingsDirty: false,
      // Whether AppSettings would accept a save right now, and whether the
      // configuration changed elsewhere while it holds unsaved edits
      appSettingsSaveState: { canSave: false, externalChange: false },
      // Unsaved settings guard: tab the user tried to leave for, held while
      // the confirmation dialog is open
      unsavedSettingsPrompt: false,
      unsavedSettingsTarget: null,
      suppressUnsavedSettingsPrompt: false,
      revertingTab: false,
      // The tab the view is actually on — `tab` transiently holds a target
      // the unsaved settings guard vetoes
      committedTab: 'home',
      // Count of outdated prompt template overrides
      promptsOutdatedCount: 0,
      // Flag to ensure new-scene navigation only happens once per scene load
      newSceneNavigationPending: false,
    }
  },
  watch:{
    availableTabs(tabs) {
      // check if tab still exists
      // in tabs
      // if not select first tab
      if(!tabs.find(tab => tab.value == this.tab)) {
        // When no scene is loaded, prefer 'home' tab
        const homeTab = tabs.find(tab => tab.value === 'home');
        this.tab = homeTab ? homeTab.value : tabs[0].value;
      }
    },
    tab: {
      handler(newTab, oldTab) {
        if(this.guardUnsavedSettings(newTab)) {
          return;
        }
        this.committedTab = newTab;

        // Save scroll position when leaving main tab
        if(oldTab === 'main' && this.sceneActive) {
          this.mainTabScrollPosition = window.scrollY;
        }
        
        // Restore scroll position when entering main tab
        if(newTab === 'main') {
          this.$nextTick(() => {
            debounce(this.onNodeEditorContainerResize, 250)();
            if(this.sceneActive) {
              setTimeout(() => {
                if(this.mainTabScrollPosition !== null) {
                  // Restore saved scroll position
                  window.scrollTo({ top: this.mainTabScrollPosition, behavior: 'smooth' });
                } else if(this.$refs.sceneMessageInput) {
                  // No saved position, scroll input field into view
                  this.$refs.sceneMessageInput.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
              }, 100);
            }
          });
        }
      }
    },
    creativeMode: {
      handler(newVal, oldVal) {
        if (newVal && !oldVal) {
          // Switching to creative mode - ensure proper resize
          this.$nextTick(() => {
            setTimeout(() => {
              debounce(this.onNodeEditorContainerResize, 50)();
            }, 100);
          });
        }
      }
    },
    sceneDrawer() {
      // debounce onNodeEditorContainerResize
      // to prevent resizing the node editor
      // too often
      debounce(this.onNodeEditorContainerResize, 250)();
    },
    directorConsoleDrawer() {
      // debounce onNodeEditorContainerResize
      // to prevent resizing the node editor
      // too often
      debounce(this.onNodeEditorContainerResize, 250)();
    },
    
    drawer() {
      // debounce onNodeEditorContainerResize
      // to prevent resizing the node editor
      // too often
      debounce(this.onNodeEditorContainerResize, 250)();
    },
    debugDrawer() {
      debounce(this.onNodeEditorContainerResize, 250)();
    },
    agentStatus: {
      // check if any of the agent's is busy in a blocking manner
      // this means agentStatus[agent].busy is true and agentStatus[agent].busy_bg is false
      handler: function() {
        let actuallyBusy = false;
        for(let agent in this.agentStatus) {
          if(this.agentStatus[agent].busy && !this.agentStatus[agent].busy_bg) {
            actuallyBusy = true;
            break;
          }
        }

        if(actuallyBusy) {
          // Immediately show busy
          this.busy = true;
          if(this.visualBusyTimer) {
            clearTimeout(this.visualBusyTimer);
            this.visualBusyTimer = null;
          }
        } else {
          // Delay clearing busy to prevent flicker
          if(!this.visualBusyTimer) {
            this.visualBusyTimer = setTimeout(() => {
              this.busy = false;
              this.visualBusyTimer = null;
            }, 800); // 800ms delay prevents most flicker
          }
        }
      },
      deep: true,
    },
  },
  computed: {
    sceneBackdropStyle() {
      if (!this.sceneBackdropSrc) {
        return {};
      }
      return { '--scene-backdrop-image': `url(${this.sceneBackdropSrc})` };
    },
    creativeMode() {
      return this.tab === 'main' && this.sceneActive && this.scene.environment === 'creative';
    },
    leftDrawerWidth() {
      // Wider drawer for the prompts tab's denser listing
      return this.tab === 'prompts' ? 400 : 300;
    },
    promptsViewPrompts() {
      // Return the prompts captured at TalemateApp level (always available)
      return this.prompts;
    },
    availableTabs() {
      return this.tabs.filter(tab => tab.condition());
    },
    sortedAgentNames() {
      // sort by label
      return Object.keys(this.agentStatus).sort((a, b) => {
        return this.agentStatus[a].label.localeCompare(this.agentStatus[b].label);
      });
    },
    sortedClientNames() {
      // sort by label
      return Object.keys(this.clientStatus).sort((a, b) => {
        return this.clientStatus[a].label.localeCompare(this.clientStatus[b].label);
      });
    },
    uxLocked() {
      // no scene loaded, not locked
      if(!this.sceneActive) {
        return false;
      }

      // if loading, ux is locked
      if(this.loading) {
        return true;
      }

      // if not waiting for input then ux is locked
      if(!this.waitingForInput) {
        return true;
      }

      return false;

    },
    effectiveAppearanceConfig() {
      // Use preview if available, otherwise fall back to saved config
      return this.appearancePreview ?? (this.appConfig ? this.appConfig.appearance : {});
    },
    rightToolsDrawerWidth() {
      // based on the current (reactive) window width, set the width of the right hand drawers
      const screenWidth = this.$vuetify.display.width;
      if(screenWidth <= 1920) {
        return 400;
      } else if(screenWidth <= 2560) {
        return 600;
      } else {
        return 800;
      }
    },
    visualAgentReady() {
      return isVisualAgentReady(this.agentStatus);
    },
    imageEditAvailable() {
      return isImageEditAvailable(this.agentStatus);
    },
    imageCreateAvailable() {
      return isImageCreateAvailable(this.agentStatus);
    },
    uxInteractionActive() {
      return this.activeUxInteractionIds.length > 0;
    },
    // True when scene direction is usable — either the director agent has it
    // enabled, or the currently-loaded scene forces it on via the intent
    // state override (`direction.always_on`). Mirrors the backend's
    // `direction_enabled_with_override` property.
    directionAvailable() {
      const agentEnabled = effectiveActionEnabled(
        this.agentStatus?.director?.actions,
        this.agentStatus?.director?.scene_overrides,
        'scene_direction',
      );
      const sceneForced = this.scene?.data?.direction_always_on || false;
      return agentEnabled || sceneForced;
    },
  },
  mounted() {
    this.connect();
    this.favicon = document.querySelector('link[rel="icon"]');
  },
  beforeUnmount() {
    // Cleanup scene assets requester (flushes any pending requests)
    if (this._sceneAssetsRequester) {
      this._sceneAssetsRequester.cleanup({ flush: true });
    }
    // Close the WebSocket connection when the component is destroyed
    if (this.websocket) {
      this.reconnect = false;
      this.websocket.close();
    }
    // Drop the asset-load rescroll listener if its window is still open
    if (this._assetLoadScrollHandler) {
      document.removeEventListener('load', this._assetLoadScrollHandler, true);
      this._assetLoadScrollHandler = null;
    }
    clearTimeout(this._assetLoadScrollTimer);
  },
  provide() {
    return {
      getWebsocket: () => this.websocket,
      registerMessageHandler: this.registerMessageHandler,
      unregisterMessageHandler: this.unregisterMessageHandler,
      isInputDisabled: () => this.isInputDisabled(),
      setInputDisabled: (disabled) => this.inputDisabled = disabled,
      isWaitingForInput: () => this.waitingForInput,
      setWaitingForInput: (waiting) => this.waitingForInput = waiting,
      isConnected: () => this.connected,
      scene: () => this.scene,
      getClients: () => this.getClients(),
      getAgents: () => this.getAgents(),
      openAgentSettings: this.openAgentSettings,
      requestSceneAssets: (asset_ids) => this.requestSceneAssets(asset_ids),
      requestAssets: (assets) => this.requestAssets(assets),
      creativeEditor: () => this.$refs.creativeEditor,
      setEnvCreative: () => this.setEnvCreative(),
      setEnvScene: () => this.setEnvScene(),
      requestAppConfig: () => this.requestAppConfig(),
      appConfig: () => this.appConfig,
      openAppConfig: this.openAppConfig,
      openAgentActionOverrides: () => this.$refs.agentActionOverrides?.open(),
      openSceneTimeline: (options) => this.$refs.sceneTimeline.open(options),
      configurationRequired: () => this.configurationRequired(),
      getTrackedCharacterState: (name, question) => this.$refs.worldState.trackedCharacterState(name, question),
      getTrackedCharacterStates: (name) => this.$refs.worldState.trackedCharacterStates(name),
      getTrackedWorldState: (question) => this.$refs.worldState.trackedWorldState(question),
      getTrackedWorldStates: () => this.$refs.worldState.trackedWorldStates(),
      getPlayerCharacterName: () => this.getPlayerCharacterName(),
      requestRegenerateLastMessage: () => this.$refs.sceneMessages?.requestRegenerateLastMessage(),
      getActAsCharacterName: () => this.actAs || this.getPlayerCharacterName(),
      formatWorldStateTemplateString: (templateString, chracterName) => this.formatWorldStateTemplateString(templateString, chracterName),
      openVisualLibraryWithAsset: (assetId, initialTab = 'info') => {
        if (this.$refs.visualLibrary && typeof this.$refs.visualLibrary.openWithAsset === 'function') {
          this.$refs.visualLibrary.openWithAsset(assetId, initialTab);
        }
      },
      addToVisualLibraryPendingQueue: (items) => {
        if (this.$refs.visualLibrary && typeof this.$refs.visualLibrary.addToPendingQueue === 'function') {
          this.$refs.visualLibrary.addToPendingQueue(items);
        }
      },
      autocompleteRequest: (partialInput, callback, focus_element, delay) => this.autocompleteRequest(partialInput, callback, focus_element, delay),
      autocompleteInfoMessage: (active) => this.autocompleteInfoMessage(active),
      toLabel: (value) => this.toLabel(value),
      openWorldStateManager: this.onOpenWorldStateManager,
      requestTemplates: () => this.requestWorldStateTemplates(),
      beginUxInteraction: (uxId) => this.beginUxInteraction(uxId),
      endUxInteraction: (uxId) => this.endUxInteraction(uxId),
      clearUxInteractions: () => this.clearUxInteractions(),
      openDebugTools: (tabValue) => {
        this.toggleNavigation('debug', true);
        this.$nextTick(() => {
          if (this.$refs.debugTools && typeof this.$refs.debugTools.selectTab === 'function') {
            this.$refs.debugTools.selectTab(tabValue);
          }
        });
      },
      callAgentTool: (actionName, args) => this.callAgentTool(actionName, args),
      openDirectorConsole: () => this.toggleNavigation('directorConsole', true),
      helpChatOpen: () => this.helpDrawer,
      openHelpChat: () => this.toggleNavigation('help', true),
      navigateToLLMTemplates: () => {
        this.tab = 'prompts';
        this.$nextTick(() => {
          this.promptsMainTab = 'llm-templates';
        });
      },
    };
  },
  methods: {
    isNewScene(sceneObj) {
      try {
        const data = sceneObj && sceneObj.data ? sceneObj.data : {};
        if (data.immutable_save) return false;
        return !data.filename;
      } catch(e) {
        console.error('Error in isNewScene()', e);
        return false;
      }
    },
    toggleSceneView(payload) {
      const wasVisible = this.showSceneView;
      this.showSceneView = !this.showSceneView;

      // If shift-click while hiding the scene view, close all drawers
      if (wasVisible && payload && payload.shiftKey) {
        this.sceneDrawer = false;
        this.drawer = false;
        this.directorConsoleDrawer = false;
        this.debugDrawer = false;
      }

      this.$nextTick(() => {
        debounce(this.onNodeEditorContainerResize, 250)();
      });
    },

    setBusy() {
      this.busy = true;
    },
    setIdle() {
      this.busy = false;
    },

    onNodeEditorContainerResize() {
      this.$nextTick(() => {
        if(!this.$refs.nodeEditorContainer) {
          return;
        }
        let width = this.$refs.nodeEditorContainer.$el.clientWidth;
        if(this.$refs.nodeEditor) {
          this.$refs.nodeEditor.resize(width);
        }
      });
    },

    connect() {

      if (this.connected || this.connecting) {
        return;
      }

      this.connecting = true;
      let currentUrl = new URL(window.location.href);
      let envWebsocketUrl = import.meta.env.VITE_TALEMATE_BACKEND_WEBSOCKET_URL;
      // Check if the env value is a valid URL (not a placeholder like ${VITE_...})
      let isValidUrl = envWebsocketUrl && envWebsocketUrl.startsWith('ws');
      if (envWebsocketUrl && !isValidUrl) {
        console.log("VITE_TALEMATE_BACKEND_WEBSOCKET_URL is set but not a valid WebSocket URL:", envWebsocketUrl);
      }
      let websocketUrl = isValidUrl ? envWebsocketUrl : `ws://${currentUrl.hostname}:5050/ws`;
      // 0.0.0.0 is a server bind address, not a reachable client target
      // (recent Chrome refuses it outright) — resolve it to whatever host
      // the UI itself was loaded from, which serves both ports.
      if (isValidUrl) {
        let wsUrl = new URL(websocketUrl);
        if (wsUrl.hostname === '0.0.0.0') {
          wsUrl.hostname = currentUrl.hostname;
          websocketUrl = wsUrl.toString();
          console.log("VITE_TALEMATE_BACKEND_WEBSOCKET_URL points at 0.0.0.0, using page hostname:", websocketUrl);
        }
      }

      console.log("urls", { websocketUrl, currentUrl }, {env : import.meta.env});

      this.websocket = new WebSocket(websocketUrl);
      console.log("Websocket connecting ...")
      this.websocket.onmessage = this.handleMessage;
      
      // Initialize scene assets requester with a sendFn that always uses current websocket
      this._sceneAssetsRequester = createSceneAssetsRequester((message) => {
        if (this.websocket) {
          this.websocket.send(JSON.stringify(message));
        }
      });
      
      this.websocket.onopen = () => {
        console.log('WebSocket connection established');
        this.connected = true;
        this.connecting = false;
        this.requestAppConfig();
        this.requestWorldStateTemplates();
        this.requestPromptOutdatedCheck();
      };
      this.websocket.onclose = (event) => {
        console.log('WebSocket connection closed', event);
        this.connected = false;
        this.connecting = false;
        this.sceneActive = false;
        this.scene = {};
        this.loading = false;
        if (this.reconnect) {
          // Wait for the configured reconnectInterval before trying again to reduce rapid retry loops
          setTimeout(() => {
            this.connect();
          }, this.reconnectInterval);
        }
      };
      this.websocket.onerror = (error) => {
        console.log('WebSocket error', error);
        // Close the WebSocket connection when an error occurs
        this.websocket.close();
        this.setNavigation('settings');
      };
    },

    registerMessageHandler(handler) {
      this.messageHandlers.push(handler);
    },

    unregisterMessageHandler(handler) {
      this.messageHandlers = this.messageHandlers.filter(h => h !== handler);
    },

    handleMessage(event) {
      const data = JSON.parse(event.data);

      this.messageHandlers.forEach(handler => handler(data));

      // Handle prompt_sent messages (capture prompts for PromptsMenu)
      if (data.type === 'prompt_sent') {
        this.handlePromptSent(data.data);
        return;
      }

      // Handle recent_templates push updates
      if (data.type === 'prompts' && data.action === 'recent_templates') {
        this.recentTemplates = data.data?.templates || [];
        return;
      }

      // Track outdated prompt template overrides
      if (data.type === 'prompts' && data.action === 'list_templates') {
        const templates = data.data?.templates || [];
        this.promptsOutdatedCount = templates.filter(t => t.is_outdated).length;
      }

      // Scene loaded
      if (data.type === "system") {
        if (data.id === 'scene.loaded') {
          this.loading = false;
          this.sceneActive = true;
          this.actAs = null;
          this.showSceneView = true;
          this.mainTabScrollPosition = null; // Reset scroll position memory for new scene
          this.newSceneNavigationPending = true; // Allow one-time new-scene navigation on next scene_status
          this.clearUxInteractions(); // Clear any active UX interactions when loading a new scene
          this.clearPrompts(); // Clear prompts when loading a new scene
          this.$refs.generationErrorDialog.closeAll(); // Backend cancelled the outgoing scene's pending generations
          this.requestAppConfig();
          this.requestWorldStateTemplates();
          this.requestPromptOutdatedCheck();
          this.$nextTick(() => {
            this.tab = 'main';
            debounce(this.onNodeEditorContainerResize, 500)();
          });
        } else if(data.id === 'scene.load_failure') {
          this.loading = false;
          this.sceneActive = false;
          this.actAs = null;
          this.scene = {};
          this.clearUxInteractions(); // Clear any active UX interactions on load failure
          this.$refs.generationErrorDialog.closeAll(); // Backend cancelled the outgoing scene's pending generations
        } else if (data.id === 'load_scene_request') {
          // Load the requested scene (e.g., after forking)
          this.resetViews();
          this.$refs.sceneLanding.loadJsonSceneFromPath(data.data.path);
        }
        if(data.status == 'error') {
          this.errorNotification = true;
          this.errorMessage = data.message;
        }
      }

      if(data.type == 'status') {
        this.notificatioonBusy = (data.status == 'busy');
      }
      
      if(data.type === 'agent_status') {
        this.setAgentStatus(data);
      }

      if(data.type === 'client_status') {
        this.setClientStatus(data);
      }

      if(data.type === 'rate_limited') {
        this.$refs.rateLimitAlert.open(data.data.client, data.data.reset_time, data.data.rate_limit);
        return;
      }

      if(data.type === 'rate_limit_reset') {
        this.$refs.rateLimitAlert.close();
        return;
      }

      if(data.type === 'auto_retry') {
        this.$refs.autoRetryAlert.open(data.data);
        return;
      }

      if(data.type === 'auto_retry_done') {
        this.$refs.autoRetryAlert.close(data.data.generation_id);
        return;
      }

      if(data.type === 'generation_error') {
        // retries exhausted - the dialog supersedes the auto-retry snackbar
        this.$refs.autoRetryAlert.close(data.data.generation_id, true);
        this.$refs.generationErrorDialog.open(data.data);
        return;
      }

      if (data.type == "scene_status") {
        this.scene = {
          name: data.name,
          title: data.data.title,
          environment: data.data.environment,
          scene_time: data.data.scene_time,
          saved: data.data.saved,
          player_character_name: data.data.player_character_name,
          data: {...data.data},
        }
        this.sceneActive = true;
        this.inactiveCharacters = data.data.inactive_characters;
        // data.data.characters is a list of all active characters in the scene
        // collect character.name into list of active characters
        this.activeCharacters = data.data.characters.map((character) => character.name);
        this.agentState = data.data.agent_state;
        this.syncActAs();

        if(this.scene.environment === 'scene') {
          // always show scene view in scene mode
          this.showSceneView = true;
        }

        // Navigate to world editor scene outline tab for new scenes (once per scene load)
        if (this.newSceneNavigationPending && this.isNewScene(this.scene)) {
          this.newSceneNavigationPending = false;
          this.onOpenWorldStateManager('scene', 'outline');
        }
        return;
      }

      if (data.type == "client_status" || data.type == "agent_status") {
        this.ready = !this.configurationRequired();
        if (!this.ready) {
          this.setNavigation('settings');
        }
        return;
      }

      if (data.type === 'app_config') {
        this.appConfig = data.data;
        if(data.version) {
          this.version = data.version;
          if (!versionsMatch(data.version)) {
            this.$refs.versionMismatchAlert.open(data.version);
          }
        }
        return;
      }

      if (this.handleAutocompleteMessage(data)) {
        return;
      }

      if (data.type === 'request_input') {

        this.waitingForInput = true;
        this.inputRequestInfo = data;

        if (data.data && data.data["input_type"] == "select") {
          // If the input_type is 'choice', send the data to SceneMessages
          this.$refs.sceneMessages.handleChoiceInput(data);
        } else {
          // Enable the input field when a request_input message comes in
          this.inputDisabled = false;
          this.$nextTick(() => {
            if (this.$refs.sceneMessageInput)
              // Highlight the user text input element when a request_input message comes in
              this.$refs.sceneMessageInput.focus();
          });
        }
      }
      
      if (data.type === 'processing_input') {
        // Disable the input field when a processing_input message comes in
        this.inputDisabled = true;
        this.inputRequestInfo = null;
        this.waitingForInput = false;
      } else if (data.type === "character" || data.type === "system") {
        this.scrollInputIntoView();
      } else if(data.type == 'world_state_manager') {
        if(data.action == 'templates') {
          this.worldStateTemplates = data.data;
          console.debug("WorldStateTemplates", this.worldStateTemplates);
        }
      }
    },

    /**
     * Updates the agentStatus object with the latest agent status data
     * 
     * This keeps track of busy and ready status of agents
     * 
     * Called when agent_status messages are received from the backend
     *
     * @param {Object} data - agent_status message data
     */
    setAgentStatus(data) {
      this.lastAgentUpdate = new Date().getTime();

      // was the agent recently busy?
      const recentlyActiveDuration = 5000;
      const lastActive = this.agentStatus[data.name] ? this.agentStatus[data.name].lastActive : null;
      const busy = data.status === 'busy_bg' || data.status === 'busy';
      const wasBusy = !busy && this.agentStatus[data.name] && this.agentStatus[data.name].busy;
      const recentlyActive = busy || wasBusy || (this.lastAgentUpdate - (lastActive || 0)) < recentlyActiveDuration;
      const recentlyActiveTimeout = this.agentStatus[data.name] ? this.agentStatus[data.name].recentlyActiveTimeout : null;

      if(recentlyActiveTimeout) {
        clearTimeout(recentlyActiveTimeout);
      }

      this.agentStatus[data.name] = {
        name: data.name,
        status: data.status,
        busy: busy,
        busy_bg: data.status === 'busy_bg',
        available: data.status === 'idle' || data.status === 'busy' || data.status === 'busy_bg',
        ready: data.status === 'idle',
        lastActive: (wasBusy || busy ? this.lastClientUpdate : lastActive),
        label: data.message,
        // active - has the agent been active in the last 5 seconds?
        recentlyActive: recentlyActive,
        details: data.client,
        meta: data.meta,
        actions: data.data.actions,
        scene_overrides: data.data.scene_overrides,
      }

      if(recentlyActive && !busy) {
        this.agentStatus[data.name].recentlyActiveTimeout = setTimeout(() => {
          this.agentStatus[data.name].recentlyActive = false;
        }, recentlyActiveDuration);
      }

      // if any agents are busy show the browser's native loading spinner in the tab
      // 
      // favicon.ico vs favicon-loading.ico

      if(Object.values(this.agentStatus).find(agent => agent.busy)) {
        if(this.favicon) {
          this.favicon.href = '/favicon-loading.ico';
        }
      } else {
        if(this.favicon) {
          this.favicon.href = '/favicon.ico';
        }
      }

    },


    /**
     * Updates the clientStatus object with the latest client status data
     * 
     * This keeps track of busy and ready status of clients
     * 
     * Called when client_status messages are received from the backend
     * 
     * @param {Object} data - client_status message data
     */
    setClientStatus(data) {
      this.lastClientUpdate = new Date().getTime();

      const recentlyActiveDuration = 15000;
      const lastActive = this.clientStatus[data.name] ? this.clientStatus[data.name].lastActive : null;
      const busy = data.status === 'busy';
      const wasBusy = !busy && this.clientStatus[data.name] && this.clientStatus[data.name].busy;
      const recentlyActive = busy || wasBusy || (this.lastClientUpdate - (lastActive || 0)) < recentlyActiveDuration;
      const recentlyActiveTimeout = this.clientStatus[data.name] ? this.clientStatus[data.name].recentlyActiveTimeout : null;

      if(recentlyActiveTimeout) {
        clearTimeout(recentlyActiveTimeout);
      }

      this.clientStatus[data.name] = {
        status: data.status,
        busy: busy,
        busy_bg: data.status === 'busy_bg',
        available: data.status === 'idle' || data.status === 'busy' || data.status === 'busy_bg',
        ready: data.status === 'idle',
        label: data.name,
        name: data.name,
        lastActive: (wasBusy || busy ? this.lastClientUpdate : lastActive),
        recentlyActive: recentlyActive,
        supports_embeddings: data.data.supports_embeddings,
        embeddings_status: data.data.embeddings_status,
      }

      if(recentlyActive && !busy) {
        this.clientStatus[data.name].recentlyActiveTimeout = setTimeout(() => {
          this.clientStatus[data.name].recentlyActive = false;
        }, recentlyActiveDuration);
      }
    },

    onInputSend({ text, actAs }) {
      this.websocket.send(JSON.stringify({ type: 'interact', text, act_as: actAs }));
      this.inputDisabled = true;
      this.waitingForInput = false;
    },

    scrollInputIntoView() {
      const scroll = () => this.$refs.sceneMessageInput?.scrollIntoView(false);
      this.$nextTick(scroll);

      // Images (character portraits, scene art) load asynchronously and can
      // push the input off-screen after our initial scroll. Listen for image
      // load events in a short window and re-scroll when they fire. Capture
      // phase is required because `load` doesn't bubble.
      if (!this._assetLoadScrollHandler) {
        this._assetLoadScrollHandler = (e) => {
          if (e.target && e.target.tagName === 'IMG') scroll();
        };
        document.addEventListener('load', this._assetLoadScrollHandler, true);
      }
      clearTimeout(this._assetLoadScrollTimer);
      this._assetLoadScrollTimer = setTimeout(() => {
        if (this._assetLoadScrollHandler) {
          document.removeEventListener('load', this._assetLoadScrollHandler, true);
          this._assetLoadScrollHandler = null;
        }
      }, 3000);
    },

    requestWorldStateTemplates() {
      this.websocket.send(JSON.stringify({
        type: 'world_state_manager',
        action: 'get_templates'
      }));
    },
    requestPromptOutdatedCheck() {
      this.websocket.send(JSON.stringify({
        type: 'prompts',
        action: 'list_templates'
      }));
    },

    syncActAs() {
      // sets the appropriate actAs

      // acting as narrator, narrator is always valid, do nothing
      if(this.actAs == "$narrator") {
        return;
      }

      // acting as a character, check if the character is still valid
      if(this.actAs && this.activeCharacters.includes(this.actAs)) {
        return;
      }

      // if actAs is null and we have characters, just leave it as null (which will default it to the player character)
      if(!this.actAs && this.activeCharacters.length > 0) {
        return;
      }

      // at this point we need a change of actAs so cycle to next option
      this.$refs.sceneMessageInput?.cycleActAs();
    },

    requestAppConfig() {
      this.websocket.send(JSON.stringify({ type: 'request_app_config' }));
    },
    saveClients(clients) {
      console.log("saveClients", clients)

      const saveData = {}

      for(let client of clients) {
        saveData[client.name] = {
          ...client,
        }
      }
      this.websocket.send(JSON.stringify({ type: 'configure_clients', clients: saveData }));
    },
    saveAgents(agents) {
      const saveData = {}

      for(let agent of agents) {
        console.log("agent", agent)
        const requiresLLM = agent.data?.requires_llm_client || false;

        let client;

        if(requiresLLM) {

          if(agent.client?.client) {
            client = agent.client?.client?.value;
          } else {
            client = agent.client || null;
          }

        } else {
          client = null;
        }

        saveData[agent.name] = {
          enabled: agent.enabled,
          actions: agent.actions,
          client: client,
        }
      }

      console.log("saveAgents",{ saveData, agents })

      this.websocket.send(JSON.stringify({ type: 'configure_agents', agents: saveData }));
    },
    requestSceneAssets(asset_ids) {
      if (this._sceneAssetsRequester) {
        this._sceneAssetsRequester.request(asset_ids);
      }
    },
    requestAssets(assets) {
      this.websocket.send(JSON.stringify({ type: 'request_assets', assets: assets }));
    },
    setNavigation(navigation) {
      if (navigation == "game")
        this.sceneDrawer = true;
      else if (navigation == "settings")
        this.drawer = true;
    },
    toggleNavigation(navigation, open) {
      if (navigation == "game")
        this.sceneDrawer = open || !this.sceneDrawer;
      else if (navigation == "settings")
        this.drawer = open || !this.drawer;
      else if (navigation == "debug")
        this.debugDrawer = open || !this.debugDrawer;
      else if (navigation == "directorConsole")
        this.directorConsoleDrawer = open || !this.directorConsoleDrawer;
      else if (navigation == "help")
        this.helpDrawer = open || !this.helpDrawer;
    },
    buildUxSnapshot() {
      // sent with help chat messages so the help agent knows what the user is looking at
      return {
        active_tab: this.tab,
        open_drawers: [
          ...(this.sceneDrawer && this.tab !== 'home' ? ['scene'] : []),
          ...(this.drawer ? ['clients_and_agents'] : []),
          ...(this.debugDrawer ? ['debug_tools'] : []),
          ...(this.directorConsoleDrawer ? ['director_console'] : []),
        ],
        scene_active: this.sceneActive,
        scene_environment: this.sceneActive ? this.scene?.environment : null,
        client_settings_modal: this.$refs.aiClient?.uxSnapshot() || null,
        agent_settings_modal: this.$refs.aiAgent?.uxSnapshot() || null,
        app_settings_modal: this.$refs.appSettings?.uxSnapshot() || null,
        app_ready: this.ready,
        waiting_for_input: this.waitingForInput,
      };
    },
    openDirectorWithChat() {
      this.toggleNavigation('directorConsole', true);
      this.websocket.send(JSON.stringify({ type: 'director', action: 'chat_create' }));
    },
    returnToStartScreen() {
      this.tab = 'home';
    },
    getClients() {
      if (!this.$refs.aiClient) {
        return [];
      }
      return this.$refs.aiClient.state.clients;
    },
    getAgents() {
      if (!this.$refs.aiAgent) {
        return [];
      }
      return this.$refs.aiAgent.state.agents;
    },
    activeClientName() {
      if (!this.$refs.aiClient) {
        return null;
      }

      let client = this.$refs.aiClient.getActive();
      if (client) {
        return client.name;
      }
      return null;
    },
    activeAgentName() {
      if (!this.$refs.aiAgent) {
        return null;
      }

      let agent = this.$refs.aiAgent.getActive();

      if (agent) {
        return agent.label;
      }
      return null;
    },
    openAgentSettings(agentName, section) {
      this.$refs.aiAgent.openSettings(agentName, section);
    },
    callAgentTool(actionName, args) {
      const dispatch = {
        openAppConfig: (...a) => this.openAppConfig(...a),
        openAgentSettings: (...a) => this.openAgentSettings(...a),
      };
      const fn = dispatch[actionName];
      if (fn) {
        fn(...(args || []));
      } else {
        console.warn('Unknown agent tool action:', actionName);
      }
    },
    configurationRequired() {
      if (!this.$refs.aiClient || this.connecting || (!this.connecting && !this.connected)) {
        return false;
      }
      return this.$refs.aiAgent.configurationRequired();
    },
    onOpenWorldStateManager(tab, sub1, sub2, sub3) {
      // If trying to open templates, redirect to templates tab instead
      // (available without a scene)
      if (tab === 'templates') {
        this.onNavigateTemplate(sub1);
        return;
      }
      if (!this.sceneActive) {
        this.worldEditorUnavailable = true;
        return;
      }
      this.tab = 'world';
      this.$nextTick(() => {
        // the unsaved settings guard can veto the switch above, leaving the
        // world window item unrendered — its commit path replays the tab's
        // click, only this sub-navigation is dropped
        this.$refs.worldStateManager?.show(tab, sub1, sub2, sub3);
      });
    },
    onOpenAgentMessages(agent_name) {
      this.$nextTick(() => {
        this.$refs.aiAgent.openMessages(agent_name);
      });
    },
    onOpenPackageManager() {
      this.tab = 'package_manager';
    },
    onNavigateTemplate(templateIndex) {
      this.tab = 'templates';
      this.$nextTick(() => {
        if(this.$refs.templates && templateIndex) {
          // If templateIndex is a template type (like 'agent_persona'), we can't directly select it
          // but we can navigate to templates tab - filtering could be added later if needed
          // For now, if it's not a valid template index format, just navigate to templates
          this.$refs.templates.selectTemplate(templateIndex);
        }
      });
    },
    onNavigatePromptTemplate(template) {
      this.$nextTick(() => {
        if (this.$refs.promptsView) {
          this.$refs.promptsView.navigateToTemplate(template.uid, template.source_group);
        }
      });
    },
    onOpenPrompt(prompt) {
      this.$nextTick(() => {
        if (this.$refs.promptsView) {
          this.$refs.promptsView.handleOpenPrompt(prompt);
        }
      });
    },
    onClearPrompts() {
      this.clearPrompts();
    },
    onTemplatesSelectionChanged(selection) {
      this.templatesSelectedGroups = selection.selectedGroups || [];
      this.templatesSelected = selection.selected || null;
    },
    onWorldStateManagerNavigateR(tab, meta) {
      this.$nextTick(() => {
        if(this.$refs.worldStateManagerMenu)
          this.$refs.worldStateManagerMenu.update(tab, meta);
      });
    },
    onWorldStateManagerSelectedCharacter(character) {
      this.$nextTick(() => {
        if(this.$refs.worldStateManagerMenu)
          this.$refs.worldStateManagerMenu.setCharacter(character)
      });
    },
    onAppearancePreview(previewConfig) {
      // Store preview config for live preview while editing
      this.appearancePreview = previewConfig;
    },
    onAppearancePreviewClear() {
      // Clear preview when settings dialog closes/cancels/saves
      this.appearancePreview = null;
    },
    onConfigureEntityHighlights() {
      // Triggered from the "Configure highlights" affordance in the entity
      // tooltip — opens the app config dialog at the scene appearance page.
      this.openAppConfig('appearance', 'scene');
    },
    openAppConfig(tab, page, item=null) {
      this.tab = 'settings';
      this.$nextTick(() => {
        if (tab && this.$refs.appSettings) {
          this.$refs.appSettings.openLegacy(tab, page, item);
        }
      });
    },
    onTabClick(tabDef) {
      // the tab's side effect acts on a view the guard may refuse to switch
      // to — leaveSettingsTab() replays it once the user commits
      if(this.settingsNavigationBlocked(tabDef.value)) {
        return;
      }
      tabDef.click();
    },
    settingsNavigationBlocked(target) {
      // leaving settings while edits are pending needs a decision first.
      // Checked against committedTab, not `tab`: v-tabs updates the model
      // before the click handler runs, so `tab` may already hold the target
      return this.committedTab === 'settings'
        && target !== 'settings'
        && this.appSettingsDirty
        && !this.suppressUnsavedSettingsPrompt;
    },
    guardUnsavedSettings(newTab) {
      // Re-entrant call caused by the revert below: the view never left the
      // settings tab, so no tab change side effect should run
      if(this.revertingTab) {
        this.revertingTab = false;
        return true;
      }
      if(!this.settingsNavigationBlocked(newTab)) {
        return false;
      }
      // hold the view on settings and let the user decide what to do with
      // the edits
      this.unsavedSettingsTarget = newTab;
      this.unsavedSettingsPrompt = true;
      this.revertingTab = true;
      this.tab = 'settings';
      return true;
    },
    onUnsavedSettingsIgnore() {
      this.leaveSettingsTab();
    },
    onUnsavedSettingsSave() {
      // fire and forget: the save is a websocket round-trip, the dirty
      // state clears (and with it the tab badge) when it comes back
      this.$refs.appSettings.saveConfig();
      this.leaveSettingsTab();
    },
    onUnsavedSettingsDiscard() {
      this.$refs.appSettings.discard();
      this.leaveSettingsTab();
    },
    leaveSettingsTab() {
      const target = this.unsavedSettingsTarget;
      this.unsavedSettingsPrompt = false;
      this.unsavedSettingsTarget = null;
      if(!target) {
        return;
      }
      // the target may have disappeared while the prompt was open (a scene
      // unload removes 'main', 'world', ...) — the availableTabs watcher
      // won't correct it, it already ran while settings (always available)
      // was selected
      const targetTab = this.availableTabs.find(tab => tab.value === target)
        || this.availableTabs.find(tab => tab.value === 'home');
      if(!targetTab) {
        return;
      }
      // the edits may still be unsaved (Ignore, or a save whose round-trip
      // hasn't landed yet) — suppress the guard so completing the navigation
      // doesn't re-open the dialog
      this.suppressUnsavedSettingsPrompt = true;
      this.tab = targetTab.value;
      this.$nextTick(() => { this.suppressUnsavedSettingsPrompt = false; });
      // take the same path a real click does — the side effect was skipped
      // when the guard vetoed the navigation
      targetTab.click();
    },
    onAppSettingsNavigate({ page, anchor }) {
      if (this.$refs.appSettings) {
        this.$refs.appSettings.navigate(page, anchor);
      }
    },
    uxErrorHandler(error) {
      this.errorNotification = true;
      this.errorMessage = error;
    },
    sceneStartedLoading() {
      this.loading = true;
      this.sceneActive = false;
      this.mainTabScrollPosition = null; // Reset scroll position memory when starting to load a new scene

      if(this.$refs.sceneMessages)
        this.$refs.sceneMessages.clear();
    },

    getPlayerCharacterName() {
      if (!this.scene || !this.scene.player_character_name) {
        return null;
      }
      return this.scene.player_character_name;
    },

    isInputDisabled() {

      // Lock interaction while a foreground agent is busy. We deliberately
      // check agent status (this.busy already excludes busy_bg) rather than
      // client status: a background agent operation — e.g. the world state
      // snapshot — keeps the shared client busy but must not lock the input.
      if (this.busy) {
        return true;
      }

      return this.inputDisabled || this.notificatioonBusy;
    },

    formatWorldStateTemplateString(templateString, chracterName) {
      let playerCharacterName = this.getPlayerCharacterName();
      // replace {character_name} and {player_name}

      if (playerCharacterName) {
        templateString = templateString.replace(/{character_name}/g, chracterName);
        templateString = templateString.replace(/{player_name}/g, playerCharacterName);
      } else {
        templateString = templateString.replace(/{character_name}/g, chracterName);
        templateString = templateString.replace(/{player_name}/g, chracterName);
      }

      return templateString;
    },

    resetViews() {
      if(this.$refs.worldStateManager)
        this.$refs.worldStateManager.reset()
    },
    toLabel(value) {
        return value.replace(/[_-]/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    },

    setEnvCreative() {
      this.websocket.send(JSON.stringify({ type: 'assistant', action: 'set_environment', environment: 'creative' }));
    },

    setEnvScene() {
      this.websocket.send(JSON.stringify({ type: 'assistant', action: 'set_environment', environment: 'scene' }));
    },

    onMessageAudioPlayed(messageId) {
      this.audioPlayedForMessageId = messageId;
    },

    onCancelAudioQueue() {
      this.audioPlayedForMessageId = undefined;
      if(this.$refs.audioQueue) {
        this.$refs.audioQueue.stopAndClear();
      }
    },

    requestNodeEditorExit() {
      this.$refs?.nodeEditor?.requestExitCreative();
    },

    beginUxInteraction(uxId) {
      if (uxId && !this.activeUxInteractionIds.includes(uxId)) {
        this.activeUxInteractionIds.push(uxId);
      }
    },

    endUxInteraction(uxId) {
      if (uxId) {
        const index = this.activeUxInteractionIds.indexOf(uxId);
        if (index > -1) {
          this.activeUxInteractionIds.splice(index, 1);
        }
      }
    },

    clearUxInteractions() {
      this.activeUxInteractionIds = [];
    },

    // Compute character-level prefix match ratio between two strings
    computePrefixMatchRatio(a, b) {
      const len = Math.min(a.length, b.length);
      let i = 0;
      while (i < len && a[i] === b[i]) i++;
      return a.length > 0 ? i / a.length : 0;
    },

    // Handle prompt_sent messages (capture prompts for PromptsMenu)
    handlePromptSent(data) {
      // agent_name here is the verbose display name (from agent_stack); the
      // canonical type+action come straight from the server now.
      let agent = null;
      let agentName = null;
      let agentAction = data.agent_action || null;

      if (data.agent_stack && data.agent_stack.length > 0) {
        agent = data.agent_stack[data.agent_stack.length - 1];
        agentName = agent.split('.')[0];
      }

      // Compute prefix cache ratio against previous prompt with same template_uid + client_name
      let prefixCacheRatio = null;
      if (data.template_uid && data.client_name && data.prompt) {
        const previous = this.prompts.find(
          p => p.template_uid === data.template_uid && p.client_name === data.client_name
        );
        if (previous && previous.prompt) {
          prefixCacheRatio = this.computePrefixMatchRatio(data.prompt, previous.prompt);
        }
      }

      this.prompts.unshift({
        prompt: data.prompt,
        response: data.response,
        kind: data.kind,
        response_tokens: data.response_tokens,
        prompt_tokens: data.prompt_tokens,
        agent_stack: data.agent_stack,
        agent: agent,
        agent_name: agentName,
        agent_type: data.agent_type || null,
        agent_action: agentAction,
        client_name: data.client_name,
        client_type: data.client_type,
        time: parseInt(data.time),
        num: this.promptTotal++,
        generation_parameters: data.generation_parameters,
        inference_preset: data.inference_preset,
        original_generation_parameters: JSON.parse(JSON.stringify(data.generation_parameters)),
        original_prompt: data.prompt,
        original_response: data.response,
        reasoning: data.reasoning,
        template_uid: data.template_uid,
        prefix_cache_ratio: prefixCacheRatio,
      });

      // Truncate if exceeds max
      while (this.prompts.length > this.maxPrompts) {
        this.prompts.pop();
      }
    },

    // Clear prompts
    clearPrompts() {
      this.prompts = [];
      this.promptTotal = 0;
    }
  }
}
</script>

<style scoped>
.backdrop {
  background-image: url('/src/assets/logo-13.1-backdrop.png');
  background-repeat: no-repeat;
  background-position: center;
  background-size: 512px 512px;
}

.backdrop-active {
  background-image: url('/src/assets/logo-13.1-backdrop.png');
  background-repeat: no-repeat;
  background-attachment: fixed;
  background-position: center;
  background-size: 512px 512px;
}

.logo {
  background-image: url('/src/assets/logo-13.1-transparent.png');
  background-repeat: no-repeat;
  background-position: center;
  background-size: fit;
  background-color: transparent;
}

.scene-container {
  flex-shrink: 0;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
  overflow-x: auto;
}

/* Scene backdrop: the scene's backdrop image (scene.assets.backdrop) fills
   the whole scene column (messages, tools and input); SceneMessages gives
   each message a translucent panel for legibility. */
.scene-backdrop-active {
  background-image: var(--scene-backdrop-image);
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  /* fixed attachment sizes/positions the image against the viewport, not
     the scene column - otherwise a long message list stretches the column
     and `cover` scales the image to the full scrollback height */
  background-attachment: fixed;
}

/* the message input, control chips (auto save, auto progress, agent
   activity, ...) and the input's send/autocomplete buttons get solid
   backgrounds so they don't fight the backdrop (they are otherwise
   transparent/tonal) */
.scene-backdrop-active .scene-controls :deep(.v-field),
.scene-backdrop-active .scene-controls :deep(.v-chip),
.scene-backdrop-active .scene-controls :deep(.scene-message-input-root .v-btn) {
  background-color: rgb(var(--v-theme-surface));
}

/* with a backdrop, stretch the scene column to at least the visible
   main-area height so a short scene doesn't crop the image; the message
   list grows and the tools/input hug the bottom of the screen.
   --v-layout-top is set by vuetify on v-main (app bar offset); the 32px
   accounts for the v-container's vertical padding. */
.scene-backdrop-active .scene-column {
  min-height: calc(100dvh - var(--v-layout-top, 64px) - 32px);
}

.scene-backdrop-active .scene-container {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
}

.scene-backdrop-active .scene-view {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.scene-controls--locked {
  pointer-events: none;
  opacity: 0.6;
}
</style>

<style>
/* dialogs opt into this while the help chat drawer is open - shifts them
   left so the drawer stays visible and usable next to them */
.v-overlay__content.yield-to-help-drawer {
  margin-right: auto;
  margin-left: 24px;
}
</style>