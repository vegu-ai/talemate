<template>
    <div>
        <div class="d-flex align-center justify-space-between clickable" role="button" tabindex="0" :aria-expanded="expanded" @click="toggle" @keydown.enter.prevent="toggle" @keydown.space.prevent="toggle">
            <div class="text-body-small font-weight-medium"><v-icon icon="mdi-function"></v-icon> {{ name }}</div>
            <v-icon size="16">{{ expanded ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
        </div>
        <v-expand-transition>
            <div v-show="expanded" class="mt-2">
                <DirectorConsoleChatMessageMarkdown v-if="details" :text="details" />
                <template v-else>
                    <div class="text-body-small mb-1" v-if="args && Object.keys(args).length">
                        <strong>Args:</strong>
                        <pre class="text-body-small" style="white-space: pre-wrap;">{{ formatJSON(args) }}</pre>
                    </div>
                    <div class="text-body-small">
                        <strong>Result:</strong>
                        <pre class="text-body-small" style="white-space: pre-wrap;">{{ formatJSON(result) }}</pre>
                    </div>
                </template>
            </div>
        </v-expand-transition>
    </div>
</template>

<script>
import DirectorConsoleChatMessageMarkdown from './DirectorConsoleChatMessageMarkdown.vue';

export default {
    name: 'DirectorConsoleChatMessageActionResult',
    components: { DirectorConsoleChatMessageMarkdown },
    props: {
        name: String,
        details: String,
        args: Object,
        result: [Object, String, Number, Boolean, Array, null],
    },
    data() {
        return {
            expanded: false,
        };
    },
    methods: {
        toggle() {
            this.expanded = !this.expanded;
        },
        formatJSON(obj) {
            try {
                return JSON.stringify(obj, null, 2);
            } catch (e) {
                return String(obj);
            }
        },
    },
}
</script>

<style scoped>
</style>
