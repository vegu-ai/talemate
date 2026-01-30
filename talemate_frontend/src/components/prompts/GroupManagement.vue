<template>
    <div class="group-management pa-3">
        <div class="text-subtitle-2 text-grey mb-2">
            <v-icon size="small" class="mr-1">mdi-sort-variant</v-icon>
            Active Groups
            <span class="text-caption">(drag to reorder priority)</span>
        </div>

        <div class="groups-container d-flex flex-wrap ga-2">
            <!-- Draggable active groups -->
            <div
                v-for="(group, index) in activeGroups"
                :key="group.name"
                class="group-chip"
                draggable="true"
                @dragstart="onDragStart($event, index)"
                @dragover.prevent="onDragOver($event, index)"
                @dragenter.prevent
                @drop="onDrop($event, index)"
                @dragend="onDragEnd"
                :class="{ 'drag-over': dragOverIndex === index }"
            >
                <v-chip
                    :color="group.name === 'user' ? 'success' : 'primary'"
                    variant="tonal"
                    label
                    closable
                    @click:close="deactivateGroup(group)"
                >
                    <v-icon start size="small">mdi-drag</v-icon>
                    {{ group.name }}
                    <v-tooltip activator="parent" location="top">
                        {{ group.template_count }} templates
                    </v-tooltip>
                </v-chip>
            </div>

            <!-- Inactive groups dropdown -->
            <v-menu v-if="inactiveGroups.length > 0">
                <template v-slot:activator="{ props }">
                    <v-btn
                        v-bind="props"
                        size="small"
                        variant="outlined"
                        color="grey"
                    >
                        <v-icon start>mdi-plus</v-icon>
                        Add Group
                    </v-btn>
                </template>
                <v-list density="compact">
                    <v-list-item
                        v-for="group in inactiveGroups"
                        :key="group.name"
                        @click="activateGroup(group)"
                    >
                        <v-list-item-title>{{ group.name }}</v-list-item-title>
                        <template v-slot:append>
                            <v-chip size="x-small" label color="grey" variant="text">
                                {{ group.template_count }}
                            </v-chip>
                        </template>
                    </v-list-item>
                </v-list>
            </v-menu>
        </div>

        <!-- Fixed groups info -->
        <div class="mt-3 text-caption text-grey">
            <v-icon size="x-small">mdi-information-outline</v-icon>
            <span v-if="sceneLoaded">
                <strong>scene</strong> always has highest priority.
            </span>
            <strong>default</strong> always has lowest priority.
        </div>
    </div>
</template>

<script>
export default {
    name: 'GroupManagement',
    props: {
        groups: {
            type: Array,
            default: () => []
        },
        priority: {
            type: Array,
            default: () => []
        },
        sceneLoaded: {
            type: Boolean,
            default: false
        }
    },
    emits: ['update:priority'],
    data() {
        return {
            dragIndex: null,
            dragOverIndex: null
        };
    },
    computed: {
        // Groups that are in the priority list (active)
        activeGroups() {
            // Return groups in priority order
            return this.priority
                .map(name => this.groups.find(g => g.name === name))
                .filter(g => g);
        },
        // Groups not in priority list and not fixed (scene/default)
        inactiveGroups() {
            const fixedGroups = ['scene', 'default'];
            return this.groups.filter(g =>
                !fixedGroups.includes(g.name) &&
                !this.priority.includes(g.name)
            );
        }
    },
    methods: {
        onDragStart(event, index) {
            this.dragIndex = index;
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', index.toString());
        },
        onDragOver(event, index) {
            this.dragOverIndex = index;
        },
        onDrop(event, toIndex) {
            const fromIndex = this.dragIndex;
            if (fromIndex !== null && fromIndex !== toIndex) {
                // Reorder the priority array
                const newPriority = [...this.priority];
                const [moved] = newPriority.splice(fromIndex, 1);
                newPriority.splice(toIndex, 0, moved);
                this.$emit('update:priority', newPriority);
            }
            this.dragIndex = null;
            this.dragOverIndex = null;
        },
        onDragEnd() {
            this.dragIndex = null;
            this.dragOverIndex = null;
        },
        activateGroup(group) {
            const newPriority = [...this.priority, group.name];
            this.$emit('update:priority', newPriority);
        },
        deactivateGroup(group) {
            const newPriority = this.priority.filter(name => name !== group.name);
            this.$emit('update:priority', newPriority);
        }
    }
};
</script>

<style scoped>
.group-chip {
    cursor: grab;
    transition: transform 0.15s ease;
}

.group-chip:active {
    cursor: grabbing;
}

.group-chip.drag-over {
    transform: scale(1.05);
}

.groups-container {
    min-height: 40px;
}
</style>
