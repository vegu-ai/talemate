<template>
  <v-app>


    <!-- scene navigation drawer -->
    <v-navigation-drawer v-model="sceneDrawer" app>
      <v-list>
        <v-alert v-if="!connected" type="error" variant="tonal">
          Not connected to Talemate backend
          <p class="text-body-2" color="white">
            Make sure the backend process is running.
          </p>
        </v-alert>
        <LoadScene ref="loadScene" @loading="sceneStartedLoading" />
        <v-divider></v-divider>
        <div :style="(sceneActive && scene.environment === 'scene' ? 'display:block' : 'display:none')">
          <!-- <GameOptions v-if="sceneActive" ref="gameOptions" /> -->
          <v-divider></v-divider>
          <CoverImage v-if="sceneActive" ref="coverImage" />
          <WorldState v-if="sceneActive" ref="worldState" />
        </div>

        <CreativeEditor v-if="sceneActive" ref="creativeEditor" />
      </v-list>

    </v-navigation-drawer>

    <!-- settings navigation drawer -->
    <v-navigation-drawer v-model="drawer" app location="right">
      <v-alert v-if="!connected" type="error" variant="tonal">
        Not connected to Talemate backend
        <p class="text-body-2" color="white">
          Make sure the backend process is running.
        </p>
      </v-alert>

      <v-list>
        <v-list-subheader class="text-uppercase"><v-icon>mdi-network-outline</v-icon>
          Clients</v-list-subheader>
        <v-list-item>
          <AIClient ref="aiClient" @save="saveClients" @error="uxErrorHandler" @clients-updated="saveClients" @client-assigned="saveAgents"></AIClient>
        </v-list-item>
        <v-divider></v-divider>
        <v-list-subheader class="text-uppercase"><v-icon>mdi-transit-connection-variant</v-icon> Agents</v-list-subheader>
        <v-list-item>
          <AIAgent ref="aiAgent" @save="saveAgents" @agents-updated="saveAgents"></AIAgent>
        </v-list-item>
        <!-- More sections can be added here -->
      </v-list>
    </v-navigation-drawer>

    <!-- debug tools navigation drawer -->
    <v-navigation-drawer v-model="debugDrawer" app location="right">
      <v-list>
        <v-list-subheader class="text-uppercase"><v-icon>mdi-bug</v-icon> Debug Tools</v-list-subheader>
        <DebugTools ref="debugTools"></DebugTools>
      </v-list>
    </v-navigation-drawer>

    <!-- system bar -->
    <v-system-bar>
      <v-icon icon="mdi-network-outline"></v-icon>
      <v-progress-circular v-if="activeAgentName() !== null" indeterminate color="primary" size="11"
        class="mr-1 ml-1"></v-progress-circular>
      <span class="mr-1">{{ activeAgentName() }}</span>
      <v-icon icon="mdi-transit-connection-variant"></v-icon>
      <v-progress-circular v-if="activeClientName() !== null" indeterminate color="primary" size="11"
        class="mr-1 ml-1"></v-progress-circular>
      <span class="mr-1">{{ activeClientName() }}</span>
      <v-divider vertical></v-divider>
      <span v-if="connecting" class="ml-1"><v-icon class="mr-1">mdi-progress-helper</v-icon>connecting</span>
      <span v-else-if="connected" class="ml-1"><v-icon class="mr-1" color="green" size="14">mdi-checkbox-blank-circle</v-icon>connected</span>
      <span v-else class="ml-1"><v-icon class="mr-1">mdi-progress-close</v-icon>disconnected</span>
      <v-divider class="ml-1 mr-1" vertical></v-divider>
      <AudioQueue ref="audioQueue" />
      <v-spacer></v-spacer>
      <span v-if="version !== null">v{{ version }}</span>
      <span v-if="configurationRequired()">
        <v-icon icon="mdi-application-cog"></v-icon>
        <span class="ml-1">Configuration required</span>
      </span>

    </v-system-bar>

    <!-- app bar -->
    <v-app-bar app>
      <v-app-bar-nav-icon @click="toggleNavigation('game')"><v-icon>mdi-script</v-icon></v-app-bar-nav-icon>
      <v-toolbar-title v-if="scene.name !== undefined">
        {{ scene.name || 'Untitled Scenario' }}
        <span v-if="scene.saved === false" class="text-red">*</span>
        <v-chip size="x-small" v-if="scene.environment === 'creative'" class="ml-2"><v-icon text="Creative" size="14"
            class="mr-1">mdi-palette-outline</v-icon>Creative Mode</v-chip>
        <v-chip size="x-small" v-else-if="scene.environment === 'scene'" class="ml-1"><v-icon text="Play" size="14"
            class="mr-1">mdi-gamepad-square</v-icon>Game Mode</v-chip>

        <v-tooltip :text="scene.scene_time" v-if="scene.scene_time !== undefined">
          <template v-slot:activator="{ props }">
            <v-btn v-bind="props" v-if="scene.environment === 'scene'" class="ml-1" @click="openSceneHistory()"><v-icon size="14"
            class="mr-1">mdi-clock</v-icon>History</v-btn>
          </template>
        </v-tooltip>

      </v-toolbar-title>
      <v-toolbar-title v-else>
        Talemate
      </v-toolbar-title>
      <v-spacer></v-spacer>
      <v-app-bar-nav-icon @click="toggleNavigation('debug')"><v-icon>mdi-bug</v-icon></v-app-bar-nav-icon>
      <v-app-bar-nav-icon @click="openAppConfig()"><v-icon>mdi-cog</v-icon></v-app-bar-nav-icon>
      <v-app-bar-nav-icon @click="toggleNavigation('settings')" v-if="configurationRequired()"
        color="red"><v-icon>mdi-application-cog</v-icon></v-app-bar-nav-icon>
      <v-app-bar-nav-icon @click="toggleNavigation('settings')"
        v-else><v-icon>mdi-application-cog</v-icon></v-app-bar-nav-icon>

    </v-app-bar>
    <v-main style="height: 100%; display: flex; flex-direction: column;">
      <v-container :class="(sceneActive ? '' : 'backdrop')" style="display: flex; flex-direction: column; height: 100%;">

        <SceneMessages ref="sceneMessages" v-if="sceneActive" />

        <div style="flex-shrink: 0;" v-if="sceneActive">

          <SceneTools @open-world-state-manager="onOpenWorldStateManager"/>
          <CharacterSheet ref="characterSheet" />
          <SceneHistory ref="sceneHistory" />

          <v-text-field
            v-model="messageInput" 
            :label="inputHint" 
            outlined 
            ref="messageInput" 
            @keyup.enter="sendMessage"
            :disabled="inputDisabled" 
            :prepend-inner-icon="messageInputIcon()"
            :color="messageInputColor()">
            <template v-slot:append>
              <v-btn @click="sendMessage" color="primary" icon>
                <v-icon v-if="messageInput">mdi-send</v-icon>
                <v-icon v-else>mdi-skip-next</v-icon>
              </v-btn>
            </template>
          </v-text-field>
        </div>
      </v-container>
    </v-main>

    <AppConfig ref="appConfig" />
    <v-snackbar v-model="errorNotification" color="red" :timeout="3000">
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
import CreativeEditor from './CreativeEditor.vue';
import AppConfig from './AppConfig.vue';
import DebugTools from './DebugTools.vue';
import AudioQueue from './AudioQueue.vue';
import StatusNotification from './StatusNotification.vue';

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
    CreativeEditor,
    AppConfig,
    DebugTools,
    AudioQueue,
    StatusNotification,
  },
  name: 'TalemateApp',
  data() {
    return {
      version: null,
      loading: false,
      sceneActive: false,
      drawer: false,
      sceneDrawer: true,
      debugDrawer: false,
      websocket: null,
      inputDisabled: false,
      waitingForInput: false,
      connectTimeout: null,
      connected: false,
      connecting: false,
      reconnect: true,
      errorMessage: null,
      errorNotification: false,
      inputHint: 'Enter your text...',
      messageInput: '',
      reconnectInterval: 3000,
      messageHandlers: [],
      scene: {},
      appConfig: {},
    }
  },
  mounted() {
    console.log("mounted!")
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
      isInputDisabled: () => this.inputDisabled,
      setInputDisabled: (disabled) => this.inputDisabled = disabled,
      isWaitingForInput: () => this.waitingForInput,
      setWaitingForInput: (waiting) => this.waitingForInput = waiting,
      isConnected: () => this.connected,
      scene: () => this.scene,
      getClients: () => this.getClients(),
      getAgents: () => this.getAgents(),
      requestSceneAssets: (asset_ids) => this.requestSceneAssets(asset_ids),
      openCharacterSheet: (characterName) => this.openCharacterSheet(characterName),
      characterSheet: () => this.$refs.characterSheet,
      creativeEditor: () => this.$refs.creativeEditor,
      requestAppConfig: () => this.requestAppConfig(),
      appConfig: () => this.appConfig,
      configurationRequired: () => this.configurationRequired(),
      getTrackedCharacterState: (name, question) => this.$refs.worldState.trackedCharacterState(name, question),
      getPlayerCharacterName: () => this.getPlayerCharacterName(),
      formatWorldStateTemplateString: (templateString, chracterName) => this.formatWorldStateTemplateString(templateString, chracterName),
    };
  },
  methods: {

    connect() {

      if (this.connected || this.connecting) {
        return;
      }

      this.connecting = true;
      let currentUrl = new URL(window.location.href);
      console.log(currentUrl);

      this.websocket = new WebSocket(`ws://${currentUrl.hostname}:5050/ws`);
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

    handleMessage(event) {
      const data = JSON.parse(event.data);

      //console.log(data);

      this.messageHandlers.forEach(handler => handler(data));

      // Scene loaded
      if (data.type === "system") {
        if (data.id === 'scene.loaded') {
          this.loading = false;
          this.sceneActive = true;
        }
        if(data.status == 'error') {
          this.errorNotification = true;
          this.errorMessage = data.message;
        }
      }

      if (data.type == "scene_status") {
        this.scene = {
          name: data.name,
          environment: data.data.environment,
          scene_time: data.data.scene_time,
          saved: data.data.saved,
          player_character_name: data.data.player_character_name,
        }
        this.sceneActive = true;
        return;
      }

      if (data.type == "client_status" || data.type == "agent_status") {
        if (this.configurationRequired()) {
          this.setNavigation('settings');
        }
        return;
      }

      if (data.type === 'app_config') {
        this.appConfig = data.data;
        this.version = data.version;
        return;
      }

      if (data.type === 'request_input') {

        this.waitingForInput = true;

        if (data.data && data.data["input_type"] == "select") {
          // If the input_type is 'choice', send the data to SceneMessages
          this.$refs.sceneMessages.handleChoiceInput(data);
        } else {
          // Enable the input field when a request_input message comes in
          this.inputDisabled = false;
          if (data.message) {
            // Update the input field hint when a request_input message with a value comes in
            this.inputHint = data.message;
          } else if (data.character) {
            // Reset the input field hint when a request_input message without a value comes in
            this.inputHint = `${data.character}:`;
          }
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
        this.waitingForInput = false;
      }
      if (data.type === "character" || data.type === "system") {
        this.$nextTick(() => {
          if (this.$refs.messageInput && this.$refs.messageInput.$el)
            this.$refs.messageInput.$el.scrollIntoView(false);
        });
      }

    },
    sendMessage() {
      if (!this.inputDisabled) {
        this.websocket.send(JSON.stringify({ type: 'interact', text: this.messageInput }));
        this.messageInput = '';
        this.inputDisabled = true;
        this.waitingForInput = false;
      }
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
      this.$refs.worldState.openWorldStateManager(tab, sub1, sub2, sub3);
    },
    openAppConfig() {
      this.$refs.appConfig.show();
    },
    uxErrorHandler(error) {
      this.errorNotification = true;
      this.errorMessage = error;
    },
    sceneStartedLoading() {
      this.loading = true;
      this.sceneActive = false;
    },

    getPlayerCharacterName() {
      if (!this.scene || !this.scene.player_character_name) {
        return null;
      }
      return this.scene.player_character_name;
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

    messageInputIcon() {
      if (this.waitingForInput) {
        if (this.inputHint != this.scene.player_character_name+":") {
          return 'mdi-information-outline';
        } else {
          return 'mdi-comment-outline';
        }
      }
      return 'mdi-cancel';
    },
    messageInputColor() {
      if (this.waitingForInput) {
        if (this.inputHint != this.scene.player_character_name+":") {
          return 'warning';
        } else {
          return 'purple-lighten-3';
        }
      }
      return null;
    }
  }
}
</script>

<style scoped>
.message.request_input {

}

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