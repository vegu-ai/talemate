<template>
    <div>
        <div class="d-flex align-center justify-space-between clickable" @click="toggle">
            <div class="text-caption font-weight-medium"><v-icon icon="mdi-function"></v-icon> {{ name }}</div>
            <v-icon size="16">{{ expanded ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
        </div>
        <v-expand-transition>
            <div v-show="expanded" class="mt-2">
                <div class="text-caption mb-1" v-if="args && Object.keys(args).length">
                    <strong>Args:</strong>
                    <pre class="text-caption" style="white-space: pre-wrap;">{{ formatJSON(args) }}</pre>
                </div>
                <div class="text-caption">
                    <strong>Result:</strong>
                    <pre class="text-caption" style="white-space: pre-wrap;">{{ formatJSON(result) }}</pre>
                </div>
            </div>
        </v-expand-transition>
    </div>
</template>

<script>
export default {
    name: 'DirectorConsoleChatMessageActionResult',
    props: {
        name: String,
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
            console.log('formatJSON', obj);
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


