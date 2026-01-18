<template>
    <v-dialog v-model="dialog" scrollable max-width="50%">
      <v-card>
        <v-tabs v-model="tab">
          <v-tab value="overview">Overview</v-tab>
          <v-tab value="details">Attributes</v-tab>
        </v-tabs>
        <v-window v-model="tab">
          <v-window-item value="overview">
            <v-card-text>
                <v-row>
                    <v-col cols="4">
                        <div v-if="cover_image">
                            <v-tooltip text="Drag and drop an image here to change the cover image for this character" max-width="200" location="bottom">
                                <template v-slot:activator="{ props }">
                            <v-img ref="coverImage" v-if="cover_image" v-bind="props" v-on:drop="onDrop" v-on:dragover.prevent :src="'data:'+media_type+';base64, '+base64"></v-img>

                                </template>
                            </v-tooltip>
                        </div>

                        <div v-else v-on:dragover.prevent v-on:drop="onDrop">
                            <v-img  src="@/assets/logo-13.1-backdrop.png" cover></v-img>
                            <v-alert type="info" variant="tonal">
                                Drag and drop an image here to set the cover image for this character
                            </v-alert>
                        </div>
                    </v-col>
                    <v-col cols="8">
                        <v-card color="grey-darken-3">
                            <v-card-title>{{ name }}</v-card-title>
                            <v-card-text>
                                <p class="pre-wrap">
                                    {{ description }}
                                </p>
                            </v-card-text>
                        </v-card>
                    </v-col>
                </v-row>
            </v-card-text>
          </v-window-item>
          <v-window-item value="details">
            <v-card-text style="max-height:600px; overflow-y:scroll;">
              <v-list-item v-for="(value, key) in base_attributes" :key="key">
                <div>
                  <v-list-item-title>{{ key }}</v-list-item-title>
                  <v-list-item-subtitle>{{ value }}</v-list-item-subtitle>
                </div>
              </v-list-item>
            </v-card-text>
          </v-window-item>
        </v-window>
      </v-card>
    </v-dialog>
  </template>
<script>
export default {
    name: 'CharacterSheet',
    data() {
        return {
            dialog: false,
            cover_image: null,
            image_base64: null,
            media_type: null,
            base_attributes: {},
            name: null,
            description: null,
            color: null,
            characters: [],
            tab: "overview",
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput', 'requestSceneAssets'],
    methods: {
        characterExists(name) {
            for (let character of this.characters) {
                // if character name is contained in name (case insensitive) and vice versa

                if (name.toLowerCase().indexOf(character.name.toLowerCase()) !== -1 || character.name.toLowerCase().indexOf(name.toLowerCase()) !== -1) {
                    return true;
                }
            }
            return false;
        },
        openForCharacter(character) {
            this.name = character.name;
            this.description = character.description;
            this.color = character.color;
            this.base_attributes = character.base_attributes;
            this.cover_image = character.cover_image;
            this.dialog = true;
            if (this.cover_image) {
                this.requestSceneAssets([this.cover_image]);
            }
        },
        openForCharacterName(name) {
            for (let character of this.characters) {
                if (name.toLowerCase().indexOf(character.name.toLowerCase()) !== -1 || character.name.toLowerCase().indexOf(name.toLowerCase()) !== -1) {
                    this.openForCharacter(character);
                    return;
                }
            }
        },
        handleMessage(data) {
            if (data.type === "scene_status" && data.status == "started") {
                this.characters = data.data.characters;
                // update the character sheet if it is open
                if (this.dialog) {
                    this.openForCharacterName(this.name);
                }
                return;
            }

            if(data.type === 'scene_asset') {
                if(data.asset_id == this.cover_image) {
                    this.base64 = data.asset;
                    this.media_type = data.media_type;
                } else {
                    this.base64 = null;
                    this.cover_image = null;
                }
                return;
            }

            if(data.type === "scene_asset_character_cover_image") {
                if(data.character == this.name) {
                    this.cover_image = null;
                    this.$nextTick(() => {
                        if(data.asset && data.asset_id) {
                            this.base64 = data.asset;
                            this.media_type = data.media_type;
                        } else if(data.asset_id && !this.base64) {
                            // Request asset if not already loaded
                            this.requestSceneAssets([data.asset_id]);
                        }
                        if(data.media_type) {
                            this.media_type = data.media_type;
                        }
                        this.cover_image = data.asset_id;
                    });

                }
                return;
            }

        },
        onDrop(e) {
            e.preventDefault();
            let files = e.dataTransfer.files;
            if (files.length > 0) {
                let reader = new FileReader();
                reader.onload = (e) => {
                    let result = e.target.result;
                    this.uploadCharacterImage(result);
                };
                reader.readAsDataURL(files[0]);
            }
        },
        uploadCharacterImage(image_file_base64) {
            this.getWebsocket().send(JSON.stringify({ 
                type: 'upload_scene_asset', 
                scene_cover_image: false,
                character_cover_image: this.name,
                content: image_file_base64,
            }));
        }
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>

.pre-wrap {
    white-space: pre-wrap;
}

</style>
```