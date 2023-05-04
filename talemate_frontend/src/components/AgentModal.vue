<template>
    <v-dialog v-model="localDialog" persistent max-width="600px">
        <v-card>
        <v-card-title>
            <span class="headline">{{ formTitle }}</span>
        </v-card-title>
        <v-card-text>
            <v-container>
              <v-row>
                  <v-col cols="6">
                    <v-text-field v-model="agent.name" readonly label="Agent"></v-text-field>
                  </v-col> 
                  <v-col cols="6">
                    <v-select v-model="agent.client" :items="agent.data.client" label="Client"></v-select>
                  </v-col>
              </v-row>
            </v-container>
        </v-card-text>
        <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn color="blue darken-1" text @click="close">Close</v-btn>
            <v-btn color="blue darken-1" text @click="save">Save</v-btn>
        </v-card-actions>
        </v-card>
    </v-dialog>
</template>
  
<script>
export default {
  props: {
    dialog: Boolean,
    formTitle: String
  },
  inject: ['state'],
  data() {
    return {
      localDialog: this.state.dialog,
      agent: { ...this.state.currentAgent }
    };
  },
  watch: {
    'state.dialog': {
      immediate: true,
      handler(newVal) {
        this.localDialog = newVal;
      }
    },
    'state.currentAgent': {
      immediate: true,
      handler(newVal) {
        this.agent = { ...newVal };
      }
    },
    localDialog(newVal) {
      this.$emit('update:dialog', newVal);
    }
  },
  methods: {
    close() {
      this.$emit('update:dialog', false);
    },
    save() {
      this.$emit('save', this.agent);
      this.close();
    }
  }
}
</script>