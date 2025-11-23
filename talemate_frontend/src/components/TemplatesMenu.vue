<template>
    <v-list density="compact" slim>
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-plus</v-icon>
            Create
        </v-list-subheader>
        <v-list-item prepend-icon="mdi-plus" @click.stop="$emit('navigate-template', '$CREATE_GROUP')">
            <v-list-item-title>Create Group</v-list-item-title>
            <v-list-item-subtitle class="text-caption">Create a new template group.</v-list-item-subtitle>
        </v-list-item>
    </v-list>
    <v-list v-for="(group, index) in safeGroups" :key="index" density="compact" slim color="primary" selectable  @update:selected="onSelectGroup" :selected="selectedGroups">
        <v-list-subheader color="grey" v-if="index === 0">
            <v-icon color="primary" class="mr-1">mdi-cube-scan</v-icon>
            Templates
        </v-list-subheader>
        <v-list-item :value="index">
            <v-icon color="primary">mdi-group</v-icon>
            {{ toLabel(group.name) }}
        </v-list-item>
        <v-card v-if="groupIsOpen(index)">
            <v-card-text class="text-grey text-caption">
                <p><span class="text-white">Author</span> <span>{{ group.author }}</span></p>
                {{ group.description }}
            </v-card-text>
        </v-card>

        <v-list v-if="groupIsOpen(index)" slim color="secondary" density="compact" selectable @update:selected="onSelect" :selected="selected">

            <!-- create template -->
            <v-list-item prepend-icon="mdi-plus" color="primary" :value="`${group.uid}__$CREATE`">
                <v-list-item-title>Create Template</v-list-item-title>
                <v-list-item-subtitle class="text-caption">Create a new template in this group.</v-list-item-subtitle>
            </v-list-item>

            <!-- templates -->
            <v-list-item v-for="(template, uid) in group.templates" :key="uid" :value="`${template.group}__${uid}`">
                <template v-slot:prepend>
                    <v-icon :color="colorForTemplate(template)">{{ iconForTemplate(template) }}</v-icon>
                </template>
                <v-list-item-title>{{ template.name }}</v-list-item-title>
                <v-list-item-subtitle class="text-caption">
                    {{ toLabel(template.template_type) }}
                </v-list-item-subtitle>
                <v-list-item-subtitle>
                    <v-chip label size="x-small" variant="outlined" class="mr-1" v-if="template.state_type">{{ template.state_type
                    }}</v-chip>
                    <v-chip v-if="template.favorite" label size="x-small" color="orange" variant="outlined"
                        class="mr-1">Favorite</v-chip>
                </v-list-item-subtitle>
            </v-list-item>
        </v-list>

    </v-list>
</template>

<script>
import { iconForTemplate, colorForTemplate } from '../utils/templateMappings.js';

export default {
    name: "TemplatesMenu",
    props: {
        templates: Object,
        selectedGroups: Array,
        selected: Array,
    },
    watch:{
        templates: {
            immediate: true,
            handler(templates) {
                if(this.deferredSelectGroup) {
                    const groups = templates?.managed?.groups || [];
                    let index = groups.findIndex(group => group.uid == this.deferredSelectGroup);
                    if(index != -1) {
                        this.$emit('update:selectedGroups', [index]);
                        this.deferredSelectGroup = null;
                    }
                }
            }
        },
        selected: {
            handler(selected) {
                if(selected && selected.length > 0) {
                    this.$emit('navigate-template', selected[0]);
                } else if(selected && selected.length === 0 && this.selectedGroups && this.selectedGroups.length > 0) {
                    // If selection cleared but group still selected, just clear template
                    this.$emit('navigate-template', this.safeGroups[this.selectedGroups[0]].uid);
                }
            }
        },
        selectedGroups: {
            handler(selectedGroups, oldSelectedGroups) {
                if(selectedGroups.length == 0) {
                    this.$emit('navigate-template', "$DESELECTED");
                    return;
                }
                let index = selectedGroups[0];
                let group = this.safeGroups[index];
                if(!oldSelectedGroups || oldSelectedGroups.length == 0 || oldSelectedGroups[0] != index) {
                    if(group) {
                        this.$emit('navigate-template', group.uid);
                    }
                }
            }
        }
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'toLabel',
    ],
    computed: {
        safeGroups() {
            return this.templates?.managed?.groups || [];
        }
    },
    data() {
        return {
            deferredSelectGroup: null,
        }
    },
    emits: [
        'navigate-template',
        'update:selectedGroups',
        'update:selected'
    ],
    methods: {
        iconForTemplate,
        colorForTemplate,
        groupIsOpen(index) {
            return this.selectedGroups && this.selectedGroups.includes(index);
        },
        onSelectGroup(value) {
            this.$emit('update:selectedGroups', value);
            // Also emit navigate immediately for group selection
            if(value.length > 0) {
                const group = this.safeGroups[value[0]];
                if(group) {
                    this.$emit('navigate-template', group.uid);
                }
            } else {
                this.$emit('navigate-template', "$DESELECTED");
            }
        },
        onSelect(value) {
            this.$emit('update:selected', value);
            // Also emit navigate immediately for template selection
            if(value && value.length > 0) {
                this.$emit('navigate-template', value[0]);
            }
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }  else if (message.action == 'template_saved') {
                let uid = message.data.template.uid;
                let group = message.data.template.group;
                const groupIndex = this.safeGroups.findIndex(g => g.uid == group);
                if(groupIndex !== -1) {
                    this.$emit('update:selectedGroups', [groupIndex]);
                    this.$emit('update:selected', [`${group}__${uid}`]);
                }
            } else if (message.action == 'template_deleted') {
                if (this.selected && this.selected[0] && this.selected[0].includes(message.data.template.uid)) {
                    this.$emit('update:selected', null);
                }
            } else if (message.action == 'template_group_saved') {
                let uid = message.data.group.uid;
                let index = this.safeGroups.findIndex(group => group.uid == uid);
                if(index == -1) {
                    this.deferredSelectGroup = uid;
                } else {
                    this.$emit('update:selectedGroups', [index]);
                }
            } else if (message.action == 'template_group_deleted') {
                if (this.selectedGroups && this.selectedGroups.length > 0) {
                    const deletedGroup = this.safeGroups[this.selectedGroups[0]];
                    if(deletedGroup && deletedGroup.uid == message.data.group.uid) {
                        this.$emit('update:selectedGroups', []);
                        this.$emit('update:selected', null);
                    }
                }
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}

</script>

