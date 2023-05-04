<template>
    <v-dialog v-model="dialog" scrollable max-width="50%" @update:model-value="submit('edit')">
        <v-window>
            <v-card density="compact">
                <v-card-text>
                    <v-select :disabled="generating" v-model="sceneContentContext" :items="contentContexts" label="Content Context"></v-select>
                    <v-textarea :disabled="generating" v-model="generationPrompt" label="AI Prompt"></v-textarea>
                </v-card-text>
                <v-card-text style="max-height:500px; overflow-y:scroll;">
                
                    <v-text-field :disabled="generating" v-model="sceneName" label="Scene Name" append-inner-icon="mdi-refresh" @click:append-inner="submit('generate_name')"></v-text-field>

                    <v-textarea :disabled="generating" v-model="sceneDescription" auto-grow label="Scene Description" append-inner-icon="mdi-refresh" @click:append-inner="submit('generate_description')"></v-textarea>

                    <v-textarea :disabled="generating" v-model="sceneIntro" auto-grow label="Scene Intro" append-inner-icon="mdi-refresh" @click:append-inner="submit('generate_intro')"></v-textarea>

                </v-card-text>
                <v-card-actions>
                    <v-progress-circular class="ml-1 mr-3" size="24" v-if="generating" indeterminate color="primary"></v-progress-circular>          
                    <v-btn color="primary" @click="submit('generate')" :disabled="generating" prepend-icon="mdi-memory">Generate</v-btn>
                </v-card-actions>
            </v-card>
        </v-window>
    </v-dialog> 
</template>

<script>
export default {
    components: {
    },
    name: 'SceneCreator',
    data() {
        return {
            dialog: false,
            sceneName: null,
            sceneDescription: null,
            sceneIntro: null,
            sceneCoverImage: null,
            sceneContentContext: null,
            contentContexts: [],
            generationPrompt: null,
            generating: false,
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput', 'requestSceneAssets', 'appConfig'],
    methods: {
        show() {
            this.dialog = true;
            this.contentContexts = this.appConfig().creator.content_context;
            this.sendRequest({
                action: 'load',
            });
        },
        exit() {
            this.dialog = false
        },
        reset() {
            this.sceneName = null;
            this.sceneDescription = null;
            this.sceneIntro = null;
            this.sceneCoverImage = null;
            this.sceneContentContext = null;
            this.generationPrompt = null;
        },

        submit(step_action) {

            if(step_action === 'generate_description')
                this.sceneDescription = null;
            else if(step_action === 'generate_intro')
                this.sceneIntro = null;
            else if(step_action === 'generate_name')
                this.sceneName = null;

            this.sendRequest({
                action: step_action,
                name: this.sceneName,
                description: this.sceneDescription,
                intro: this.sceneIntro,
                content_context: this.sceneContentContext,
                prompt: this.generationPrompt,
            });
        },

        sendRequest(data) {
            data.type = 'scene_creator';
            this.getWebsocket().send(JSON.stringify(data));
        },

        handleSetGenerating() {
            this.generating = true;
        },

        handleSetGeneratingDone() {
            this.generating = false;
        },

        handleMessage(data) {

            if(data.type === 'scene_creator') {
                if(data.action === 'set_generating') {
                    this.handleSetGenerating();
                } else if(data.action === 'set_generating_done') {
                    this.handleSetGeneratingDone();
                } else if(data.action === 'scene_update') {
                    this.sceneDescription = data.description;
                    this.sceneIntro = data.intro;
                    this.sceneName = data.name;
                }
                return;
            }

        },

    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped></style>