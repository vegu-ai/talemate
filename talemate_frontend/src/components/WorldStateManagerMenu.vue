<template>
    <v-list-item>
        <v-list-item-title>
            {{ scene.title }}
        </v-list-item-title>
        <v-list-item-subtitle>
            World Editor
        </v-list-item-subtitle>
    </v-list-item>
    <v-list-item>
        <v-tabs density="compact" v-model="tab" color="primary" direction="vertical">
            <v-tab v-for="tab in tabs" :disabled="tab.disabled" :key="tab.name" @click="emitNavigate(tab.name)" :text="tab.title" :prepend-icon="tab.icon" :value="tab.name">
            </v-tab>
        </v-tabs>
    </v-list-item>
</template>

<script>

export default {
    name: 'WorldStateManagerMenu',
    props: {
        scene: Object
    },
    data() {
        return {
            tab: "characters",
            tabs: [
                {
                    name: "scene",
                    title: "Scene",
                    icon: "mdi-script"
                },
                {
                    name: "characters",
                    title: "Characters",
                    icon: "mdi-account-group"
                },
                {
                    name: "world",
                    title: "World",
                    icon: "mdi-earth"
                },
                {
                    name: "history",
                    title: "History",
                    icon: "mdi-clock",
                    disabled: true,
                },
                {
                    name: "contextdb",
                    title: "Context",
                    icon: "mdi-book-open-page-variant"
                },
                {
                    name: "pins",
                    title: "Pins",
                    icon: "mdi-pin"
                },
                {
                    name: "templates",
                    title: "Templates",
                    icon: "mdi-cube-scan"
                },
                {
                    name: "game",
                    title: "Game Master",
                    icon: "mdi-dice-multiple",
                    disabled: true,
                },
            ]
        }

    },
    emits: [
        'world-state-manager-navigate'
    ],
    inject: ['getWebsocket', 'registerMessageHandler', 'isConnected'],
    methods: {
        emitNavigate(tab) {
            this.$emit('world-state-manager-navigate', tab);
        }
    }
}

</script>