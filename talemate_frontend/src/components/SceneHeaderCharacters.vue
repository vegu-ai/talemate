<template>
    <div class="scene-header-characters" role="group" aria-label="Active characters">
        <v-tooltip v-for="character in characters" :key="character.name" :text="character.name" location="bottom">
            <template v-slot:activator="{ props }">
                <button
                    v-bind="props"
                    type="button"
                    class="scene-header-characters__circle"
                    :style="circleStyle(character)"
                    :aria-label="`Open ${character.name} in the World Editor`"
                    @click="open(character.name)">
                    <img v-if="portraitSrc(character)" :src="portraitSrc(character)" alt="" class="scene-header-characters__portrait" />
                    <span v-else aria-hidden="true">{{ character.initial }}</span>
                </button>
            </template>
        </v-tooltip>
        <v-menu v-if="hidden.length" v-model="moreOpen" location="bottom end">
            <template v-slot:activator="{ props: menuProps }">
                <v-tooltip :text="`${hidden.length} more: ${hiddenNames}`" location="bottom" max-width="320" :disabled="moreOpen">
                    <template v-slot:activator="{ props: tooltipProps }">
                        <button
                            v-bind="mergeProps(menuProps, tooltipProps)"
                            type="button"
                            class="scene-header-characters__circle scene-header-characters__more"
                            :aria-label="`${hidden.length} more characters`">
                            +{{ hidden.length }}
                        </button>
                    </template>
                </v-tooltip>
            </template>
            <v-list density="compact">
                <v-list-item v-for="character in hidden" :key="character.name" :title="character.name" @click="open(character.name)">
                    <template v-slot:prepend>
                        <span class="scene-header-characters__circle scene-header-characters__circle--list mr-3" :style="circleStyle(character)" aria-hidden="true">
                            <img v-if="portraitSrc(character)" :src="portraitSrc(character)" alt="" class="scene-header-characters__portrait" />
                            <span v-else>{{ character.initial }}</span>
                        </span>
                    </template>
                </v-list-item>
            </v-list>
        </v-menu>
    </div>
</template>

<script>
import { mergeProps } from 'vue';
import VisualAssetsMixin from './VisualAssetsMixin.js';
import { readableTextOn } from '@/utils/cssColor';

export default {
    name: 'SceneHeaderCharacters',
    mixins: [VisualAssetsMixin],
    inject: ['openWorldStateManager'],
    props: {
        // [{ name, color, avatar, initial }] from the Active characters item
        characters: { type: Array, default: () => [] },
        hidden: { type: Array, default: () => [] },
        scene: { type: Object, default: () => ({}) },
    },
    data() {
        return {
            moreOpen: false,
        };
    },
    computed: {
        avatarIds() {
            return [...this.characters, ...this.hidden].map((character) => character.avatar).filter(Boolean);
        },
        hiddenNames() {
            return this.hidden.map((character) => character.name).join(', ');
        },
        // what the header paints behind the row (at 85% over a backdrop)
        headerBackground() {
            return this.$vuetify.theme.current.colors.background;
        },
    },
    watch: {
        // the open list unmounts with the last hidden character; a stale true would reopen it on the next overflow
        'hidden.length'(count) {
            if (!count) this.moreOpen = false;
        },
        avatarIds: {
            handler(ids) {
                this.loadAssets(ids);
            },
            immediate: true,
        },
    },
    created() {
        this.registerMessageHandler(this.handleSceneAssetMessage);
    },
    beforeUnmount() {
        this.unregisterMessageHandler(this.handleSceneAssetMessage);
    },
    methods: {
        mergeProps,
        portraitSrc(character) {
            return character.avatar ? this.getAssetSrc(character.avatar) : '';
        },
        circleStyle(character) {
            if (this.portraitSrc(character)) return {};
            return { backgroundColor: character.color, color: readableTextOn(character.color, this.headerBackground) || undefined };
        },
        open(name) {
            this.openWorldStateManager('characters', name, 'description');
        },
    },
};
</script>

<style scoped>
.scene-header-characters {
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

.scene-header-characters__circle {
    width: 26px;
    height: 26px;
    flex: 0 0 26px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border-radius: 50%;
    overflow: hidden;
    border: 1px solid rgba(var(--v-theme-on-background), 0.24);
    font-size: 0.8125rem;
    font-weight: 600;
    line-height: 1;
    color: rgba(var(--v-theme-on-background), var(--v-high-emphasis-opacity));
    background-color: rgba(var(--v-theme-on-background), 0.08);
    cursor: pointer;
}

.scene-header-characters__circle:focus-visible {
    outline: 2px solid rgb(var(--v-theme-primary));
    outline-offset: 2px;
}

.scene-header-characters__circle--list {
    cursor: inherit;
}

.scene-header-characters__more {
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
}

.scene-header-characters__portrait {
    width: 100%;
    height: 100%;
    object-fit: cover;
}
</style>
