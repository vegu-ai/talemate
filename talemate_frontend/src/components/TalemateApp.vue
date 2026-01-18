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
      <v-app-bar-nav-icon size="small" @click="toggleNavigation('game')">
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
        <v-tab v-for="tab in availableTabs" :key="tab" :value="tab.value" @click.stop="tab.click">
          <v-icon class="mr-1">{{ tab.icon() }}</v-icon>
          {{ tab.title() }}
        </v-tab>
      </v-tabs>
  
      <v-spacer></v-spacer>

      <DirectorConsoleWidget :scene-active="sceneActive" @open-director-console="toggleNavigation('directorConsole')" />

      <VoiceLibrary :scene-active="sceneActive" :scene="scene" :app-busy="busy" :app-ready="ready" v-if="agentStatus.tts?.available"/>

      <VisualLibrary ref="visualLibrary" :scene-active="sceneActive" :scene="scene" :app-busy="busy" :app-ready="ready" :agent-status="agentStatus" :world-state-templates="worldStateTemplates"/>

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
      <v-navigation-drawer v-model="sceneDrawer" app width="300">
        <v-alert v-if="!connected" type="error" variant="tonal">
          Not connected to Talemate backend
          <p class="text-body-2" color="white">
            Make sure the backend process is running.
          </p>
        </v-alert>
        <v-alert type="warning" variant="tonal" v-if="!ready && connected">There are some outstanding configuration issues, please ensure that all enabled agents are configured correctly.</v-alert>
        <v-tabs-window v-model="tab">
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="home">
            <LoadScene 
            ref="loadScene" 
            :scene-loading-available="ready && connected"
            :world-state-templates="worldStateTemplates"
            @loading="sceneStartedLoading" />
          </v-tabs-window-item>
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
          <v-list-subheader class="text-uppercase"><v-icon>mdi-transit-connection-variant</v-icon> Agents</v-list-subheader>
          <AIAgent ref="aiAgent" @save="saveAgents" @agents-updated="saveAgents" :agentState="agentState" :templates="worldStateTemplates" :app-config="appConfig"></AIAgent>
          <!-- More sections can be added here -->
        </v-list>
      </v-navigation-drawer>

      <!-- director console navigation drawer -->
      <v-navigation-drawer v-model="directorConsoleDrawer" app location="right" :width="directorConsoleWidth" disable-resize-watcher>
        <DirectorConsole :scene="scene" v-if="sceneActive" :app-busy="busy" :app-ready="ready" :open="directorConsoleDrawer" />
      </v-navigation-drawer>

      <!-- debug tools navigation drawer -->
      <v-navigation-drawer v-model="debugDrawer" app location="right" width="400" disable-resize-watcher>
        <v-list>
          <v-list-subheader class="text-uppercase"><v-icon>mdi-bug</v-icon> Debug Tools</v-list-subheader>
          <DebugTools ref="debugTools" :scene="scene"></DebugTools>
        </v-list>
      </v-navigation-drawer>

      <v-container :class="(sceneActive ? '' : 'backdrop')" fluid style="height: 100%;">

        <v-tabs-window v-model="tab" style="height: 100%;">
          <!-- HOME -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="home">
            <IntroView
            ref="introView"
            @request-scene-load="(path) => {  resetViews(); $refs.loadScene.loadJsonSceneFromPath(path); }"
            @request-backup-restore="(restoreInfo) => { resetViews(); $refs.loadScene.loadJsonSceneFromPath(restoreInfo.scenePath, false, restoreInfo.backupPath, restoreInfo.rev); }"
            :version="version" 
            :scene-loading-available="ready && connected"
            :scene-is-loading="loading"
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
              <v-col :cols="creativeMode ? (showSceneView ? 6 : 0) : 12"  :xl="creativeMode ? (showSceneView ? 4 : 12) : 12" :class="{ 'pl-2': true, 'd-none': creativeMode && !showSceneView }">
                <div style="display: flex; flex-direction: column; height: 100%">

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

                    <div v-show="showSceneView">
                      <SceneMessages
                        ref="sceneMessages"
                        :appearance-config="effectiveAppearanceConfig"
                        :ux-locked="uxLocked"
                        :agent-status="agentStatus"
                        :audio-played-for-message-id="audioPlayedForMessageId"
                        :scene="scene"
                        @cancel-audio-queue="onCancelAudioQueue"
                      />
                    </div>

                    <div ref="sceneToolsContainer" :class="{ 'scene-controls--locked': uxInteractionActive }">
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
                        :audioPlayedForMessageId="audioPlayedForMessageId" />
                      <CharacterSheet ref="characterSheet" />
                      <v-textarea
                        v-model="messageInput" 
                        :label="messageInputHint()" 
                        rows="1"
                        auto-grow
                        outlined 
                        ref="messageInput" 
                        @keydown.enter.prevent="sendMessage"
                        @keydown.ctrl.up.prevent="onHistoryUp"
                        @keydown.ctrl.down.prevent="onHistoryDown"
                        @keydown.tab.prevent="cycleActAs"
                        :hint="messageInputLongHint()"
                        :disabled="busy || !ready || uxInteractionActive || isInputDisabled()"
                        :loading="autocompleting"
                        :prepend-inner-icon="messageInputIcon()"
                        :color="messageInputColor()">
                        <template v-slot:prepend v-if="sceneActive && scene.environment !== 'creative'">
                          <!-- auto-complete button -->
                          <v-btn @click="autocomplete" color="primary" icon variant="tonal" :disabled="!messageInput || busy || !ready || uxInteractionActive || isInputDisabled()">
                            <v-icon>mdi-auto-fix</v-icon>
                          </v-btn>
                        </template>
                        <template v-slot:append>
                          <!-- send message button -->
                          <v-btn @click="sendMessage" color="primary" icon variant="tonal" :disabled="busy || !ready || uxInteractionActive || isInputDisabled()">
                            <v-icon v-if="messageInput">mdi-send</v-icon>
                            <v-icon v-else>mdi-skip-next</v-icon>
                          </v-btn>
                        </template>
                      </v-textarea>
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
            ref="templates"
            @selection-changed="onTemplatesSelectionChanged" />
          </v-tabs-window-item>

        </v-tabs-window>

      </v-container>
    </v-main>

    <AppConfig ref="appConfig" :agentStatus="agentStatus" :sceneActive="sceneActive" :clientStatus="clientStatus" @appearance-preview="onAppearancePreview" @appearance-preview-clear="onAppearancePreviewClear" />
    <v-snackbar v-model="errorNotification" color="red-darken-1" :timeout="3000">
        {{ errorMessage }}
    </v-snackbar>
  </v-app>
  <StatusNotification />
  <RateLimitAlert ref="rateLimitAlert" />
  <NewSceneSetupModal
    v-if="sceneActive"
    v-model="showNewSceneSetup"
    :scene="scene"
    :templates="worldStateTemplates"
    @open-director="toggleNavigation('directorConsole', true)"
  />
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
import LoadScene from './LoadScene.vue';
import SceneTools from './SceneTools.vue';
import SceneMessages from './SceneMessages.vue';
import WorldState from './WorldState.vue';
import CoverImage from './CoverImage.vue';
import CharacterSheet from './CharacterSheet.vue';
import AppConfig from './AppConfig.vue';
import DebugTools from './DebugTools.vue';
import AudioQueue from './AudioQueue.vue';
import StatusNotification from './StatusNotification.vue';
import RateLimitAlert from './RateLimitAlert.vue';
import VisualLibrary from './VisualLibrary.vue';
import VoiceLibrary from './VoiceLibrary.vue';
import WorldStateManager from './WorldStateManager.vue';
import WorldStateManagerMenu from './WorldStateManagerMenu.vue';
import IntroView from './IntroView.vue';
import NodeEditor from './NodeEditor.vue';
import DirectorConsole from './DirectorConsole.vue';
import DirectorConsoleWidget from './DirectorConsoleWidget.vue';
import PackageManager from './PackageManager.vue';
import PackageManagerMenu from './PackageManagerMenu.vue';
import NewSceneSetupModal from './NewSceneSetupModal.vue';
import Templates from './Templates.vue';
import TemplatesMenu from './TemplatesMenu.vue';
import OnboardingWizard from './OnboardingWizard.vue';
// import debounce
import { debounce } from 'lodash';
import { isVisualAgentReady, isImageEditAvailable, isImageCreateAvailable } from '../constants/visual.js';
import { createSceneAssetsRequester } from './VisualAssetsMixin.js';

const INPUT_HISTORY_MAX = 10;

export default {
  components: {
    AIClient,
    AIAgent,
    AgentActivityBar,
    LoadScene,
    SceneTools,
    SceneMessages,
    WorldState,
    CoverImage,
    CharacterSheet,
    AppConfig,
    DebugTools,
    AudioQueue,
    StatusNotification,
    IntroView,
    VisualLibrary,
    WorldStateManager,
    WorldStateManagerMenu,
    NodeEditor,
    DirectorConsole,
    RateLimitAlert,
    DirectorConsoleWidget,
    PackageManager,
    PackageManagerMenu,
    VoiceLibrary,
    NewSceneSetupModal,
    Templates,
    TemplatesMenu,
    OnboardingWizard,
  },
  name: 'TalemateApp',
  data() {
    return {
      appearancePreview: null, // Preview config while editing settings (null = use saved config)
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
              this.$refs.messageInput.$el.scrollIntoView(false);
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
      autocompleting: false,
      autocompletePartialInput: "",
      autocompleteCallback: null,
      autocompleteFocusElement: null,
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
      showNewSceneSetup: false,
      newSceneSetupShownForId: null,
      // input history state
      inputHistory: [],
      historyIndex: 0, // 0 = draft, -1 = most recent history, -2 = older, ...
      draftBeforeHistoryBrowse: '',
      templatesSelectedGroups: [],
      templatesSelected: null,
      mainTabScrollPosition: null,
      // Scene assets requester (initialized when websocket is available)
      _sceneAssetsRequester: null,
      // Track active UX interaction IDs (for disabling scene controls during UX interactions)
      activeUxInteractionIds: [],
      
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
                } else if(this.$refs.messageInput && this.$refs.messageInput.$el) {
                  // No saved position, scroll input field into view
                  this.$refs.messageInput.$el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
    creativeMode() {
      return this.tab === 'main' && this.sceneActive && this.scene.environment === 'creative';
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
    directorConsoleWidth() {
      // based on the screen width, set the width of the director console
      const screenWidth = window.innerWidth;
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
    }
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
      openCharacterSheet: (characterName) => this.openCharacterSheet(characterName),
      characterSheet: () => this.$refs.characterSheet,
      creativeEditor: () => this.$refs.creativeEditor,
      setEnvCreative: () => this.setEnvCreative(),
      setEnvScene: () => this.setEnvScene(),
      requestAppConfig: () => this.requestAppConfig(),
      appConfig: () => this.appConfig,
      openAppConfig: this.openAppConfig,
      configurationRequired: () => this.configurationRequired(),
      getTrackedCharacterState: (name, question) => this.$refs.worldState.trackedCharacterState(name, question),
      getTrackedWorldState: (question) => this.$refs.worldState.trackedWorldState(question),
      getPlayerCharacterName: () => this.getPlayerCharacterName(),
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
    };
  },
  methods: {
    isNewScene(sceneObj) {
      try {
        const data = sceneObj && sceneObj.data ? sceneObj.data : {};
        const title = (data.title || '').trim();
        const titleUnset = !title || ['new scenario', 'untitled scenario'].includes(title.toLowerCase());
        const descriptionUnset = !(data.description || '').trim();
        const contextUnset = !(data.context || '').trim();
        const introUnset = !(data.intro || '').trim();
        return titleUnset && descriptionUnset && contextUnset && introUnset;
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

      // Scene loaded
      if (data.type === "system") {
        if (data.id === 'scene.loaded') {
          this.loading = false;
          this.sceneActive = true;
          this.actAs = null;
          this.showSceneView = true;
          this.mainTabScrollPosition = null; // Reset scroll position memory for new scene
          this.clearUxInteractions(); // Clear any active UX interactions when loading a new scene
          this.requestAppConfig();
          this.requestWorldStateTemplates();
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
        } else if (data.id === 'load_scene_request') {
          // Load the requested scene (e.g., after forking)
          this.resetViews();
          this.$refs.loadScene.loadJsonSceneFromPath(data.data.path);
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

        // Detect new scene and open setup modal (only once per unique scene id)
        try {
          const sceneId = this.scene && this.scene.data ? (this.scene.data.id || null) : null;
          const guardId = sceneId || this.scene.name; // fallback to name if id not provided

          if (this.isNewScene(this.scene)) {
            if (this.newSceneSetupShownForId !== guardId) {
              this.showNewSceneSetup = true;
              this.newSceneSetupShownForId = guardId;
              // Also navigate to world editor scene outline tab for new scenes
              this.onOpenWorldStateManager('scene', 'outline');
            }
          } else {
            // reset so future truly-new scenes can show the modal again
            this.newSceneSetupShownForId = null;
          }
        } catch(e) {
          console.error('Error detecting new scene', e);
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
        if(data.version)
          this.version = data.version;
        return;
      }

      if (data.type === 'autocomplete_suggestion') {

        if(!this.autocompleteCallback)
          return;

        const completion = data.message;
        this.autocompleteCallback(completion);

        if (this.autocompleteFocusElement) {
          let focus_element = this.autocompleteFocusElement;
          setTimeout(() => {
            focus_element.focus();
          }, 1000);
          this.autocompleteFocusElement = null;
        }

        this.autocompleteCallback = null;
        this.autocompletePartialInput = "";
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
            if (this.$refs.messageInput)
              // Highlight the user text input element when a request_input message comes in
              this.$refs.messageInput.focus();
          });
        }
      }
      
      if (data.type === 'processing_input') {
        // Disable the input field when a processing_input message comes in
        this.inputDisabled = true;
        this.inputRequestInfo = null;
        this.waitingForInput = false;
      } else if (data.type === "character" || data.type === "system") {
        this.$nextTick(() => {
          if (this.$refs.messageInput && this.$refs.messageInput.$el)
            this.$refs.messageInput.$el.scrollIntoView(false);
        });
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

    isWaitingForDialogInput() {
      return this.waitingForInput && this.inputRequestInfo && this.inputRequestInfo.reason === "talk";
    },

    autocomplete() {
      if(!this.isWaitingForDialogInput()) {
        return;
      }

      this.autocompleting = true
      this.inputDisabled = true;

      let context = "dialogue:player";

      if(this.actAs) {
        if(this.actAs === "$narrator") {
          context = `narrative:`;
        } else {
          context = `dialogue:${this.actAs}`;
        }
      }

      this.autocompleteRequest(
        {
          partial: this.messageInput,
          context: context,
          character: this.actAs,
        }, 
        (completion) => {
          this.inputDisabled = false
          this.autocompleting = false
          this.messageInput += completion;
        },
        this.$refs.messageInput,
        100,
      );
    },

    sendMessage(event) {

      // if ctrl+enter is pressed, request autocomplete
      if (event.ctrlKey && event.key === 'Enter') {
        return this.autocomplete();
      }

      if (this.uxInteractionActive) {
        return;
      }

      // if shift+enter is pressed, add a newline at the current cursor position
      if (event.shiftKey && event.key === 'Enter') {
        const textarea = this.$refs.messageInput.$el.querySelector('textarea');
        const cursorPos = textarea.selectionStart;
        this.messageInput = this.messageInput.slice(0, cursorPos) + "\n" + this.messageInput.slice(cursorPos);
        // Set cursor position after the inserted newline
        this.$nextTick(() => {
          textarea.selectionStart = textarea.selectionEnd = cursorPos + 1;
        });
        return;
      }

      if (!this.inputDisabled) {
        const sentText = this.messageInput;
        this.websocket.send(JSON.stringify({ type: 'interact', text: sentText, act_as: this.actAs}));
        // store to history (max 10)
        const trimmed = (sentText || '').trim();
        if (trimmed.length > 0) {
          this.inputHistory.unshift(sentText);
          if (this.inputHistory.length > INPUT_HISTORY_MAX) {
            this.inputHistory.length = INPUT_HISTORY_MAX;
          }
        }
        this.draftBeforeHistoryBrowse = '';
        this.historyIndex = 0;
        this.messageInput = '';
        this.inputDisabled = true;
        this.waitingForInput = false;
      }
    },

    requestWorldStateTemplates() {
      this.websocket.send(JSON.stringify({ 
        type: 'world_state_manager',
        action: 'get_templates'
      }));
    },

    onHistoryUp(event) {
      if (!this.inputHistory || this.inputHistory.length === 0) {
        return;
      }
      const maxUp = this.inputHistory.length;
      if (this.historyIndex <= -maxUp) {
        return; // already at oldest
      }
      if (this.historyIndex === 0) {
        this.draftBeforeHistoryBrowse = this.messageInput;
      }
      this.historyIndex -= 1;
      const historyPos = -this.historyIndex - 1; // 0-based into inputHistory
      const value = this.inputHistory[historyPos] ?? '';
      this.messageInput = value;
      this.$nextTick(() => {
        const textarea = this.$refs.messageInput?.$el?.querySelector('textarea');
        if (textarea) {
          const len = value.length;
          textarea.selectionStart = textarea.selectionEnd = len;
        }
      });
    },

    onHistoryDown(event) {
      if (this.historyIndex === 0) {
        return; // do not wrap
      }
      this.historyIndex += 1;
      if (this.historyIndex === 0) {
        const value = this.draftBeforeHistoryBrowse || '';
        this.messageInput = value;
        this.$nextTick(() => {
          const textarea = this.$refs.messageInput?.$el?.querySelector('textarea');
          if (textarea) {
            const len = value.length;
            textarea.selectionStart = textarea.selectionEnd = len;
          }
        });
        return;
      }
      const historyPos = -this.historyIndex - 1;
      if (historyPos < 0 || historyPos >= this.inputHistory.length) {
        // Clamp, although logic should prevent this
        this.historyIndex = 0;
        return;
      }
      const value = this.inputHistory[historyPos] ?? '';
      this.messageInput = value;
      this.$nextTick(() => {
        const textarea = this.$refs.messageInput?.$el?.querySelector('textarea');
        if (textarea) {
          const len = value.length;
          textarea.selectionStart = textarea.selectionEnd = len;
        }
      });
    },

    autocompleteRequest(param, callback, focus_element, delay=500) {

      this.autocompleteCallback = (completion) => {
        setTimeout(() => {
          callback(completion);
        }, delay);
      };
      this.autocompleteFocusElement = focus_element;
      this.autocompletePartialInput = param.partial;

      const param_copy = JSON.parse(JSON.stringify(param));
      param_copy.type = "assistant";
      param_copy.action = "autocomplete";

      this.websocket.send(JSON.stringify(param_copy));
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
      this.cycleActAs();
    },

    cycleActAs() {

      // will cycle through activeCharacters, which is a dict of character names
      // and set actAs to the next character name in the list
      //
      // if actAs is null it means the player is acting as themselves

      const playerCharacterName = this.getPlayerCharacterName();

      // if there are no characters, set actAs to $narrator
      if(!this.activeCharacters || this.activeCharacters.length === 0) {
        this.actAs = "$narrator";
        return;
      }

      // if current actAs is $narrator, set actAs to the first character in the list
      if(this.actAs === "$narrator") {
        this.actAs = null;
        return;
      }

      let selectedCharacter = null;
      let foundActAs = false;

      for(let characterName of this.activeCharacters) {
        // actAs is $narrator so we take the first character in the list
        if(this.actAs === "$narrator") {
          selectedCharacter = characterName;
          break;
        }
        // actAs is null, so we take the first character in the list that is not
        // the player character
        if(this.actAs === null && characterName !== playerCharacterName) {
          selectedCharacter = characterName;
          break;
        }
        // actAs is set, so we find the first non player character after the current actAs
        // if actAs is the last character in the list, we set actAs to null
        if(foundActAs) {
          selectedCharacter = characterName;
          break;
        } else {
          if(characterName === this.actAs) {
            foundActAs = true;
          }
        }
      }

      if(selectedCharacter === null || selectedCharacter === playerCharacterName) {
        this.actAs = "$narrator";
      } else {
        this.actAs = selectedCharacter;
      }
    },

    autocompleteInfoMessage(active) {
      return active ? 'Generating ...' : "Ctrl+Enter to autocomplete";
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
    configurationRequired() {
      if (!this.$refs.aiClient || this.connecting || (!this.connecting && !this.connected)) {
        return false;
      }
      return this.$refs.aiAgent.configurationRequired();
    },
    openCharacterSheet(characterName) {
      this.$refs.characterSheet.openForCharacterName(characterName);
    },
    onOpenWorldStateManager(tab, sub1, sub2, sub3) {
      // If trying to open templates, redirect to templates tab instead
      if (tab === 'templates') {
        this.onNavigateTemplate(sub1);
        return;
      }
      this.tab = 'world';
      this.$nextTick(() => {
        this.$refs.worldStateManager.show(tab, sub1, sub2, sub3);
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
          if(templateIndex.includes('__') || templateIndex === '$CREATE_GROUP' || templateIndex === '$DESELECTED') {
            this.$refs.templates.selectTemplate(templateIndex);
          }
          // Otherwise, it might be a template type filter - just show templates tab
        }
      });
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
    openAppConfig(tab, page, item=null) {
      this.$refs.appConfig.show(tab, page, item);
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

      // if any client is active and busy, disable input
      if (this.$refs.aiClient && this.$refs.aiClient.getActive()) {
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

    messageInputHint() {
      if(this.waitingForInput) {

        if(this.inputRequestInfo.reason === "talk") {

          let characterName = this.actAs ? this.actAs : this.scene.player_character_name;

          if(characterName === "$narrator")
            return "Narrator:";

          return `${characterName}:`;
        }

        return this.inputRequestInfo.message;
      }
      return "";
    },

    messageInputLongHint() {
      const DIALOG_HINT = "Ctrl+Enter to autocomplete, Shift+Enter for newline, Ctrl+Up/Down for history, Tab to act as another character. Start messages with '@' to do an action. (e.g., '@look at the door')";

      if(this.waitingForInput) {
        if(this.inputRequestInfo.reason === "talk") {
          return DIALOG_HINT;
        }
      }
      return "";
    },

    messageInputIcon() {
      if (this.waitingForInput) {
        if (this.inputRequestInfo.reason != "talk") {
          return 'mdi-information-outline';
        } else {
          if(this.actAs === '$narrator')
            return 'mdi-script-text-outline';
          return 'mdi-comment-outline';
        }
      }
      return 'mdi-cancel';
    },

    messageInputColor() {
      if (this.waitingForInput) {
        if (this.inputRequestInfo.reason != "talk") {
          return 'warning';
        } else {

          if(!this.scene || !this.scene.data || !this.scene.data.character_colors || !this.scene.data.character_colors[this.scene.player_character_name]) {
            return "primary";
          }

          if(this.actAs) {

            if(this.actAs === "$narrator")
              return "narrator";

            return this.scene.data.character_colors[this.actAs];
          }
          return this.scene.data.character_colors[this.scene.player_character_name];
        }
      }
      return null;
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

.scene-controls--locked {
  pointer-events: none;
  opacity: 0.6;
}
</style>