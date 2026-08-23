<template>
    <v-sheet v-if="displayPaths.length" class="game-state-knobs mb-2" rounded="lg" border>
        <v-tooltip text="Scene gamestate controls" location="top">
            <template v-slot:activator="{ props }">
                <v-icon v-bind="props" color="primary" size="small">mdi-tune-variant</v-icon>
            </template>
        </v-tooltip>
        <GameStateValueInput
            v-for="path in displayPaths"
            :key="path"
            class="game-state-knob"
            :path="path"
            :label="getGameStatePathLabel(scene, knobPaths, path)"
            :value="getValueAtPath(path)"
            :disabled="disabled"
            @update-value="updateValueAtPath(path, $event)"
        />
    </v-sheet>
</template>

<script>
import GameStateValueInput from './GameStateValueInput.vue';
import {
    expandGameStatePaths,
    getGameStatePathLabel,
    getGameStateValue,
} from '@/utils/gameStatePaths.js';

export default {
    name: 'GameStateKnobs',
    components: {
        GameStateValueInput,
    },
    inject: ['getWebsocket'],
    props: {
        scene: {
            type: Object,
            default: () => ({}),
        },
        disabled: Boolean,
    },
    computed: {
        knobPaths() {
            return this.scene?.data?.game_state_knob_paths || [];
        },
        gameStateVariables() {
            return this.scene?.data?.game_state?.variables || {};
        },
        displayPaths() {
            return expandGameStatePaths(this.knobPaths, this.gameStateVariables);
        },
    },
    methods: {
        getGameStatePathLabel,
        getValueAtPath(path) {
            return getGameStateValue(this.gameStateVariables, path);
        },
        updateValueAtPath(path, newValue) {
            this.getWebsocket().send(JSON.stringify({
                type: 'devtools',
                action: 'set_game_state_variable',
                path,
                value: newValue,
            }));
        },
    },
};
</script>

<style scoped>
.game-state-knobs {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 8px;
    background-color: rgb(var(--v-theme-surface));
}

.game-state-knob {
    flex: 1 1 180px;
    min-width: 150px;
    max-width: 260px;
}
</style>
