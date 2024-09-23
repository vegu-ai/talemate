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
      <AudioQueue ref="audioQueue" />
      <v-spacer></v-spacer>
      <span v-if="version !== null" class="text-grey text-caption">v{{ version }}</span>
      <span v-if="!ready">
        <v-icon icon="mdi-application-cog"></v-icon>
        <span class="ml-1">Configuration required</span>
      </span>

    </v-system-bar>

    <!-- app bar -->
    <v-app-bar app density="compact">
      <v-app-bar-nav-icon size="x-small" @click="toggleNavigation('game')">
        <v-icon v-if="sceneDrawer">mdi-arrow-collapse-left</v-icon>
        <v-icon v-else>mdi-arrow-collapse-right</v-icon>
      </v-app-bar-nav-icon>
      
      <v-tabs v-model="tab" color="primary">
        <v-tab v-for="tab in availableTabs" :key="tab" :value="tab.value" @click.stop="tab.click">
          <v-icon class="mr-1">{{ tab.icon() }}</v-icon>
          {{ tab.title() }}
        </v-tab>
      </v-tabs>
  
      <v-spacer></v-spacer>

      <VisualQueue ref="visualQueue" />
      <v-app-bar-nav-icon @click="toggleNavigation('debug')"><v-icon>mdi-bug</v-icon></v-app-bar-nav-icon>
      <v-app-bar-nav-icon @click="openAppConfig()"><v-icon>mdi-cog</v-icon></v-app-bar-nav-icon>
      <v-app-bar-nav-icon @click="toggleNavigation('settings')" v-if="!ready"
        color="red-darken-1"><v-icon>mdi-application-cog</v-icon></v-app-bar-nav-icon>
      <v-app-bar-nav-icon @click="toggleNavigation('settings')"
        v-else><v-icon>mdi-application-cog</v-icon></v-app-bar-nav-icon>

    </v-app-bar>

    <v-main style="height: 100%; display: flex; flex-direction: column;">

      <!-- left side navigation drawer -->
      <v-navigation-drawer v-model="sceneDrawer" app width="300">
        <v-alert v-if="!connected" type="error" variant="tonal">
          Not connected to Talemate backend
          <p class="text-body-2" color="white">
            Make sure the backend process is running.
          </p>
        </v-alert>
        <v-tabs-window v-model="tab">
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="home">
            <v-alert type="warning" variant="tonal" v-if="!ready && connected">You need to configure a Talemate client before you can load scenes.</v-alert>
            <LoadScene 
            ref="loadScene" 
            :scene-loading-available="ready && connected"
            @loading="sceneStartedLoading" />
          </v-tabs-window-item>
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="main">
            <CoverImage v-if="sceneActive" ref="coverImage" />
            <WorldState v-if="sceneActive" ref="worldState" @passive-characters="(characters) => { passiveCharacters = characters }"  @open-world-state-manager="onOpenWorldStateManager"/>
          </v-tabs-window-item>
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="world">
            <WorldStateManagerMenu v-if="sceneActive"
            ref="worldStateManagerMenu" 
            :scene="scene"
            :worldStateTemplates="worldStateTemplates"
            @world-state-manager-navigate="onOpenWorldStateManager" 
            />
          </v-tabs-window-item>
        </v-tabs-window>
      </v-navigation-drawer>
      <!-- right side navigation drawer -->
      <v-navigation-drawer v-model="drawer" app location="right" width="300" disable-resize-watcher>
        <v-alert v-if="!connected" type="error" variant="tonal">
          Not connected to Talemate backend
          <p class="text-body-2" color="white">
            Make sure the backend process is running.
          </p>
        </v-alert>

        <v-list>
          <AIClient ref="aiClient" @save="saveClients" @error="uxErrorHandler" @clients-updated="saveClients" @client-assigned="saveAgents" @open-app-config="openAppConfig"></AIClient>
          <v-divider></v-divider>
          <v-list-subheader class="text-uppercase"><v-icon>mdi-transit-connection-variant</v-icon> Agents</v-list-subheader>
          <AIAgent ref="aiAgent" @save="saveAgents" @agents-updated="saveAgents"></AIAgent>
          <!-- More sections can be added here -->
        </v-list>
      </v-navigation-drawer>

      <!-- debug tools navigation drawer -->
      <v-navigation-drawer v-model="debugDrawer" app location="right" width="400" disable-resize-watcher>
        <v-list>
          <v-list-subheader class="text-uppercase"><v-icon>mdi-bug</v-icon> Debug Tools</v-list-subheader>
          <DebugTools ref="debugTools"></DebugTools>
        </v-list>
      </v-navigation-drawer>


      <v-container :class="(sceneActive ? '' : 'backdrop')" fluid style="height: 100%;">

        <v-tabs-window v-model="tab" style="height: 100%;">
          <!-- HOME -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="home">
            <IntroView
            ref="introView"
            @request-scene-load="(path) => {  resetViews(); $refs.loadScene.loadJsonSceneFromPath(path); }"
            :version="version" 
            :scene-loading-available="ready && connected"
            :config="appConfig" />
          </v-tabs-window-item>
          <!-- SCENE -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="main" style="height: 100%;">
            <div style="display: flex; flex-direction: column; height: 100%">

              <div v-if="sceneActive && scene.environment === 'creative' && !scene.data.intro">
                <v-alert color="muted" class="mb-2" variant="text">
                  <v-alert-title>New Scene</v-alert-title>
                  You're editing a new scene. Select the <v-btn @click="onOpenWorldStateManager('scene')" variant="text" size="small" color="primary" prepend-icon="mdi-earth-box">World Editor</v-btn> to add characters and scene details. You are currently operating in the creative environment. Once you have added at least one player character you may switch back and forth between creative and gameplay mode at any point using the <v-icon color="primary" size="small">mdi-gamepad-square</v-icon> button at the bottom.
                  <p class="mt-4">
                    You can still use the world editor while in gameplay mode as well.
                  </p>
                </v-alert>
              </div>

              <SceneMessages ref="sceneMessages" />
              <div style="flex-shrink: 0;">
      
                <SceneTools 
                  @open-world-state-manager="onOpenWorldStateManager"
                  :messageInput="messageInput"
                  :agent-status="agentStatus"
                  :worldStateTemplates="worldStateTemplates"
                  :playerCharacterName="getPlayerCharacterName()"
                  :passiveCharacters="passiveCharacters"
                  :inactiveCharacters="inactiveCharacters"
                  :activeCharacters="activeCharacters" />
                <CharacterSheet ref="characterSheet" />
                <SceneHistory ref="sceneHistory" />
                <v-textarea
                  v-model="messageInput" 
                  :label="messageInputHint()" 
                  rows="1"
                  auto-grow
                  outlined 
                  ref="messageInput" 
                  @keydown.enter.prevent="sendMessage"
                  @keydown.tab.prevent="cycleActAs"
                  :hint="messageInputLongHint()"
                  :disabled="isInputDisabled()"
                  :loading="autocompleting"
                  :prepend-inner-icon="messageInputIcon()"
                  :color="messageInputColor()">
                  <template v-slot:append>
                    <v-btn @click="sendMessage" color="primary" icon>
                      <v-icon v-if="messageInput">mdi-send</v-icon>
                      <v-icon v-else>mdi-skip-next</v-icon>
                    </v-btn>
                  </template>
                </v-textarea>
              </div>
            </div>

          </v-tabs-window-item>
          <!-- WORLD -->
          <v-tabs-window-item :transition="false" :reverse-transition="false" value="world">
            <WorldStateManager 
            :world-state-templates="worldStateTemplates"
            :scene="scene"
            :agent-status="agentStatus"
            :app-config="appConfig"
            @navigate-r="onWorldStateManagerNavigateR"
            @selected-character="onWorldStateManagerSelectedCharacter"
            ref="worldStateManager" />
          </v-tabs-window-item>

        </v-tabs-window>

      </v-container>
    </v-main>

    <AppConfig ref="appConfig" :agentStatus="agentStatus" :sceneActive="sceneActive" />
    <v-snackbar v-model="errorNotification" color="red-darken-1" :timeout="3000">
        {{ errorMessage }}
    </v-snackbar>
    <StatusNotification />
  </v-app>
</template>
  
<script>
import AIClient from './AIClient.vue';
import AIAgent from './AIAgent.vue';
import LoadScene from './LoadScene.vue';
import SceneTools from './SceneTools.vue';
import SceneMessages from './SceneMessages.vue';
import WorldState from './WorldState.vue';
//import GameOptions from './GameOptions.vue';
import CoverImage from './CoverImage.vue';
import CharacterSheet from './CharacterSheet.vue';
import SceneHistory from './SceneHistory.vue';
import AppConfig from './AppConfig.vue';
import DebugTools from './DebugTools.vue';
import AudioQueue from './AudioQueue.vue';
import StatusNotification from './StatusNotification.vue';
import VisualQueue from './VisualQueue.vue';
import WorldStateManager from './WorldStateManager.vue';
import WorldStateManagerMenu from './WorldStateManagerMenu.vue';
import IntroView from './IntroView.vue';

export default {
  components: {
    AIClient,
    AIAgent,
    LoadScene,
    SceneTools,
    SceneMessages,
    WorldState,
    //GameOptions,
    CoverImage,
    CharacterSheet,
    SceneHistory,
    AppConfig,
    DebugTools,
    AudioQueue,
    StatusNotification,
    IntroView,
    VisualQueue,
    WorldStateManager,
    WorldStateManagerMenu,
  },
  name: 'TalemateApp',
  data() {
    return {
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
      sceneActive: false,
      drawer: false,
      sceneDrawer: true,
      debugDrawer: false,
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
      agentStatus: {},
      clientStatus: {},
      // timestamps for last agent and client updates
      // received from the backend
      lastAgentUpdate: null,
      lastClientUpdate: null,
    }
  },
  watch:{
    availableTabs(tabs) {
      // check if tab still exists
      // in tabs
      // if not select first tab
      if(!tabs.find(tab => tab.value == this.tab)) {
        this.tab = tabs[0].value;
      }
    }
  },
  computed: {
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
    }
  },
  mounted() {
    this.connect();
  },
  beforeUnmount() {
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
      requestSceneAssets: (asset_ids) => this.requestSceneAssets(asset_ids),
      requestAssets: (assets) => this.requestAssets(assets),
      openCharacterSheet: (characterName) => this.openCharacterSheet(characterName),
      characterSheet: () => this.$refs.characterSheet,
      creativeEditor: () => this.$refs.creativeEditor,
      requestAppConfig: () => this.requestAppConfig(),
      appConfig: () => this.appConfig,
      configurationRequired: () => this.configurationRequired(),
      getTrackedCharacterState: (name, question) => this.$refs.worldState.trackedCharacterState(name, question),
      getTrackedWorldState: (question) => this.$refs.worldState.trackedWorldState(question),
      getPlayerCharacterName: () => this.getPlayerCharacterName(),
      formatWorldStateTemplateString: (templateString, chracterName) => this.formatWorldStateTemplateString(templateString, chracterName),
      autocompleteRequest: (partialInput, callback, focus_element) => this.autocompleteRequest(partialInput, callback, focus_element),
      autocompleteInfoMessage: (active) => this.autocompleteInfoMessage(active),
      toLabel: (value) => this.toLabel(value),
    };
  },
  methods: {

    connect() {

      if (this.connected || this.connecting) {
        return;
      }

      this.connecting = true;
      let currentUrl = new URL(window.location.href);
      let websocketUrl = process.env.VUE_APP_TALEMATE_BACKEND_WEBSOCKET_URL || `ws://${currentUrl.hostname}:5050/ws`;

      console.log("urls", { websocketUrl, currentUrl }, {env : process.env});

      this.websocket = new WebSocket(websocketUrl);
      console.log("Websocket connecting ...")
      this.websocket.onmessage = this.handleMessage;
      this.websocket.onopen = () => {
        console.log('WebSocket connection established');
        this.connected = true;
        this.connecting = false;
        this.requestAppConfig();
      };
      this.websocket.onclose = (event) => {
        console.log('WebSocket connection closed', event);
        this.connected = false;
        this.connecting = false;
        this.sceneActive = false;
        this.scene = {};
        this.loading = false;
        if(this.reconnect)
          this.connect();
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
          this.requestAppConfig();
          this.requestWorldStateTemplates();
          this.$nextTick(() => {
            this.tab = 'main';
          });
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

        // append completion to messageInput, add a space if
        // neither messageInput ends with a space nor completion starts with a space
        // unless completion starts with !, ., or ?

        const completionStartsWithSentenceEnd = completion.startsWith('!') || completion.startsWith('.') || completion.startsWith('?') || completion.startsWith(')') || completion.startsWith(']') || completion.startsWith('}') || completion.startsWith('"') || completion.startsWith("'") || completion.startsWith("*") || completion.startsWith(",")

        if (this.autocompletePartialInput.endsWith(' ') || completion.startsWith(' ') || completionStartsWithSentenceEnd) {
          this.autocompleteCallback(completion);
        } else {
          this.autocompleteCallback(' ' + completion);
        }

        if (this.autocompleteFocusElement) {
          let focus_element = this.autocompleteFocusElement;
          setTimeout(() => {
            focus_element.focus();
          }, 200);
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
      }

      if(recentlyActive && !busy) {
        this.agentStatus[data.name].recentlyActiveTimeout = setTimeout(() => {
          this.agentStatus[data.name].recentlyActive = false;
        }, recentlyActiveDuration);
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
        lastActive: (wasBusy || busy ? this.lastClientUpdate : lastActive),
        recentlyActive: recentlyActive,
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

    sendMessage(event) {

      // if ctrl+enter is pressed, request autocomplete
      if (event.ctrlKey && event.key === 'Enter') {

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
          this.$refs.messageInput
        );
        return;
      }

      // if shift+enter is pressed, add a newline
      if (event.shiftKey && event.key === 'Enter') {
        this.messageInput += "\n";
        return;
      }

      if (!this.inputDisabled) {
        this.websocket.send(JSON.stringify({ type: 'interact', text: this.messageInput, act_as: this.actAs}));
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

    autocompleteRequest(param, callback, focus_element) {

      this.autocompleteCallback = callback;
      this.autocompleteFocusElement = focus_element;
      this.autocompletePartialInput = param.partial;

      const param_copy = JSON.parse(JSON.stringify(param));
      param_copy.type = "assistant";
      param_copy.action = "autocomplete";

      this.websocket.send(JSON.stringify(param_copy));
    },

    cycleActAs() {

      // will cycle through activeCharacters, which is a dict of character names
      // and set actAs to the next character name in the list
      //
      // if actAs is null it means the player is acting as themselves

      const playerCharacterName = this.getPlayerCharacterName();

      // if current actAs is $narrator, set actAs to the first character in the list
      if(this.actAs === "$narrator") {
        this.actAs = null;
        return;
      }

      let selectedCharacter = null;

      for(let characterName of this.activeCharacters) {
        if(this.actAs === null && characterName === playerCharacterName)  {
          continue;
        }
        if(this.actAs === characterName) {
          continue;
        }
        selectedCharacter = characterName;
        break;
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
      this.websocket.send(JSON.stringify({ type: 'configure_clients', clients: clients }));
    },
    saveAgents(agents) {
      console.log({ type: 'configure_agents', agents: agents })
      this.websocket.send(JSON.stringify({ type: 'configure_agents', agents: agents }));
    },
    requestSceneAssets(asset_ids) {
      this.websocket.send(JSON.stringify({ type: 'request_scene_assets', asset_ids: asset_ids }));
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
    toggleNavigation(navigation) {
      if (navigation == "game")
        this.sceneDrawer = !this.sceneDrawer;
      else if (navigation == "settings")
        this.drawer = !this.drawer;
      else if (navigation == "debug")
        this.debugDrawer = !this.debugDrawer;
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
    configurationRequired() {
      if (!this.$refs.aiClient || this.connecting || (!this.connecting && !this.connected)) {
        return false;
      }
      return this.$refs.aiAgent.configurationRequired();
    },
    openCharacterSheet(characterName) {
      this.$refs.characterSheet.openForCharacterName(characterName);
    },
    openSceneHistory() {
      this.$refs.sceneHistory.open();
    },
    onOpenWorldStateManager(tab, sub1, sub2, sub3) {
      this.tab = 'world';
      console.log("onOpenWorldStateManager", {tab, sub1, sub2, sub3})
      console.trace("onOpenWorldStateManager", {tab, sub1, sub2, sub3})
      this.$nextTick(() => {
        this.$refs.worldStateManager.show(tab, sub1, sub2, sub3);
      });
    },
    onWorldStateManagerNavigateR(tab, meta) {
      console.trace("onWorldStateManagerNavigateR", {tab, meta})
      this.$nextTick(() => {
        if(this.$refs.worldStateManagerMenu)
          this.$refs.worldStateManagerMenu.update(tab, meta);
      });
    },
    onWorldStateManagerSelectedCharacter(character) {
      console.trace("onWorldStateManagerSelectedCharacter", character)
      this.$nextTick(() => {
        if(this.$refs.worldStateManagerMenu)
          this.$refs.worldStateManagerMenu.setCharacter(character)
      });
    },
    openAppConfig(tab, page) {
      this.$refs.appConfig.show(tab, page);
    },
    uxErrorHandler(error) {
      this.errorNotification = true;
      this.errorMessage = error;
    },
    sceneStartedLoading() {
      this.loading = true;
      this.sceneActive = false;

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
      const DIALOG_HINT = "Ctrl+Enter to autocomplete, Shift+Enter for newline, Tab to act as another character";

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

</style>