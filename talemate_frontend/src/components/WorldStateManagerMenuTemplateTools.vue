<template>
    <v-list density="compact" slim>
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-plus</v-icon>
            Create
        </v-list-subheader>
        <v-list-item prepend-icon="mdi-plus" @click.stop="$emit('world-state-manager-navigate', 'templates', '$CREATE_GROUP')">
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

export default {
    name: "WorldStateManagerMenuTemplateTools",
    components: {
    },
    props: {
        scene: Object,
        title: String,
        icon: String,
        worldStateTemplates: Object,
        manager: Object,
    },
    watch:{
        worldStateTemplates: {
            immediate: true,
            handler(worldStateTemplates) {
                if(this.deferredSelectGroup) {
                    const groups = worldStateTemplates?.managed?.groups || [];
                    let index = groups.findIndex(group => group.uid == this.deferredSelectGroup);
                    if(index != -1) {
                        this.selectedGroups = [index];
                        this.deferredSelectGroup = null;
                    }
                }
            }
        },
        selected: {
            immediate: true,
            handler(selected) {
                this.$emit('world-state-manager-navigate', 'templates', selected ? selected[0] : null);
            }
        },
        selectedGroups: {
            immediate: true,
            handler(selectedGroups, oldSelectedGroups) {
                if(selectedGroups.length == 0) {
                    this.$emit('world-state-manager-navigate', 'templates', "$DESELECTED");
                    return;
                }
                let index = selectedGroups[0];
                let group = this.safeGroups[index];
                if(!oldSelectedGroups.length || oldSelectedGroups[0] != index) {
                    this.$emit('world-state-manager-navigate', 'templates', group.uid);
                }
            }
        }
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    computed: {
        safeGroups() {
            return this.worldStateTemplates?.managed?.groups || [];
        }
    },
    data() {
        return {
            selectedGroups: [],
            confirmDelete: null,
            deleteBusy: false,
            characterList: {
                characters: [],
            },
            selected: null,
            deferredSelectGroup: null,
        }
    },
    emits: [
        'world-state-manager-navigate'
    ],
    methods: {
        iconForTemplate(template) {
            if(this.manager && this.manager.getEditor('templates')) {
                return this.manager.getEditor('templates').iconForTemplate(template);
            }
            return 'mdi-cube-scan';
        },
        colorForTemplate(template) {
            if(this.manager && this.manager.getEditor('templates')) {
                return this.manager.getEditor('templates').colorForTemplate(template);
            }
            return null;
        },
        toLabel(value) {
            return value.replace(/[_-]/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        },
        groupIsOpen(index) {
            return this.selectedGroups.includes(index);
        },
        onSelectGroup(value) {
            this.selectedGroups = value;
        },
        onSelect(value) {
            this.selected = value;
        },
        deleteGroup(index) {
            let group = this.safeGroups[index];
            if(!group) {
                return;
            }
            let confirmed = confirm(`Are you sure you want to delete the group "${group.name}"?`);
            if (!confirmed) {
                return;
            }

        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }  else if (message.action == 'template_saved') {
                let uid = message.data.template.uid;
                let group = message.data.template.group;
                this.selectedGroups = [this.safeGroups.findIndex(group => group.uid == message.data.template.group)]
                this.selected = [`${group}__${uid}`]
            } else if (message.action == 'template_deleted') {
                if (this.selected == message.data.template.uid) {
                    this.selected = null;
                }
            } else if (message.action == 'template_group_saved') {
                let uid = message.data.group.uid;
                let index = this.safeGroups.findIndex(group => group.uid == uid);
                if(index == -1) {
                    this.deferredSelectGroup = uid;
                } else {
                    this.selectedGroups = [index]
                }
            } else if (message.action == 'template_group_deleted') {
                if (this.selectedGroups == message.data.group.uid) {
                    this.selectedGroups = null;
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