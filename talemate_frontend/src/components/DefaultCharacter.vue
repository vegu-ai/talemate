<template>
  <v-dialog v-model="showModal" max-width="800px">
    <v-card>
      <v-card-title class="headline">Your Character</v-card-title>
      <v-card-text>
        <v-alert type="info" variant="tonal" v-if="defaultCharacter.name === ''" density="compact">You have not yet
          configured a default player character. This character will be used when a scenario is loaded that does not come
          with a pre-defined player character.</v-alert>
        <v-container>
          <v-row>
            <v-col cols="12" sm="6">
              <v-text-field v-model="defaultCharacter.name" label="Name" :rules="[rules.required]"></v-text-field>
            </v-col>
            <v-col cols="12" sm="6">
              <v-text-field v-model="defaultCharacter.gender" label="Gender" :rules="[rules.required]"></v-text-field>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12">
              <v-textarea v-model="defaultCharacter.description" label="Description" auto-grow></v-textarea>
            </v-col>
          </v-row>
        </v-container>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="primary" v-if="!saving" text @click="cancel" prepend-icon="mdi-cancel">Cancel</v-btn>
        <v-progress-circular v-else indeterminate="disable-shrink" color="primary" size="20"></v-progress-circular>
        <v-btn color="primary" text :disabled="saving" @click="saveDefaultCharacter" prepend-icon="mdi-check-circle-outline">Continue</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'DefaultCharacter',
  inject: ['getWebsocket', 'registerMessageHandler'],
  data() {
    return {
      showModal: false,
      saving: false,
      defaultCharacter: {
        name: '',
        gender: '',
        description: '',
        color: '#3362bb'
      },
      rules: {
        required: value => !!value || 'Required.'
      }
    };
  },
  methods: {
    saveDefaultCharacter() {
      // Send the new default character data to the server
      this.saving = true;
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: 'save_default_character',
        data: this.defaultCharacter
      }));
    },
    cancel() {
      this.$emit("cancel");
      this.closeModal();
    },
    open() {
      this.saving = false;
      this.showModal = true;
    },
    closeModal() {
      this.showModal = false;
    },
    handleMessage(message) {
      if (message.type == 'config') {
        if (message.action == 'save_default_character_complete') {
          this.closeModal();
          this.$emit("save");
        }
      }
    },
  },
  created() {
    this.registerMessageHandler(this.handleMessage);
  },
};
</script>

<style scoped>
/* Add any specific styles for your DefaultCharacter modal here */
</style>
