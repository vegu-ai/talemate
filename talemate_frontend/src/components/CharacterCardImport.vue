<template>
  <v-dialog v-model="showModal" max-width="600px" persistent>
    <v-card>
      <v-card-title class="headline">
        <v-icon class="mr-2" color="primary">mdi-account-multiple</v-icon>
        Character Card Import Options
      </v-card-title>
      <v-card-text>
        <v-alert type="info" variant="tonal" density="compact" class="mb-4">
          Configure how the character card should be imported.
        </v-alert>
        <v-container>
          <v-row>
            <v-col cols="12">
              <v-switch
                v-model="options.import_all_characters"
                label="Import All Characters"
                hint="If enabled, all detected characters will be imported. Otherwise, only the first character will be imported."
                persistent-hint
                color="primary"
              ></v-switch>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12">
              <v-switch
                v-model="options.import_character_book"
                label="Import Character Book"
                hint="If enabled, character book entries will be imported into world state."
                persistent-hint
                color="primary"
              ></v-switch>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12">
              <v-switch
                v-model="options.import_character_book_meta"
                label="Import Character Book Metadata"
                hint="If enabled, character book metadata will be included in manual context entries."
                persistent-hint
                color="primary"
                :disabled="!options.import_character_book"
              ></v-switch>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12">
              <v-switch
                v-model="options.import_alternate_greetings"
                label="Import Alternate Greetings"
                hint="If enabled, alternate greetings will be set as scene intro versions."
                persistent-hint
                color="primary"
              ></v-switch>
            </v-col>
          </v-row>
        </v-container>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="primary" text @click="cancel" prepend-icon="mdi-cancel">Cancel</v-btn>
        <v-btn color="primary" text @click="confirm" prepend-icon="mdi-check-circle-outline">Import</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'CharacterCardImport',
  data() {
    return {
      showModal: false,
      options: {
        import_all_characters: false,
        import_character_book: true,
        import_character_book_meta: true,
        import_alternate_greetings: true,
      },
      resolveCallback: null,
    };
  },
  methods: {
    open() {
      // Reset to defaults
      this.options = {
        import_all_characters: false,
        import_character_book: true,
        import_character_book_meta: true,
        import_alternate_greetings: true,
      };
      this.showModal = true;
      return new Promise((resolve) => {
        this.resolveCallback = resolve;
      });
    },
    confirm() {
      this.showModal = false;
      if (this.resolveCallback) {
        this.resolveCallback({ confirmed: true, options: { ...this.options } });
        this.resolveCallback = null;
      }
    },
    cancel() {
      this.showModal = false;
      if (this.resolveCallback) {
        this.resolveCallback({ confirmed: false });
        this.resolveCallback = null;
      }
    },
  },
};
</script>

<style scoped>
/* Add any specific styles for CharacterCardImport modal here */
</style>

