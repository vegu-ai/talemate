<template>
    <div v-if="templatesAvailable">
        <v-list density="compact" slim v-model:opened="groupsOpen">
            <v-list-item :disabled="busy || selectedTemplates.length === 0" @click.stop="applySelected">
                <template v-slot:prepend>
                    <v-icon v-if="!busy">mdi-expand-all</v-icon>
                </template>
                <v-list-item-title>Apply Selected</v-list-item-title>
                <v-list-item-subtitle>Apply all selected templates.</v-list-item-subtitle>
            </v-list-item>
            <div>
                <v-list-group fluid v-for="(group, index) in viableTemplates" :key="index" :value="group.group.uid">
                    <template v-slot:activator="{ props }">
                        <v-list-item v-bind="props" class="text-muted"
                            :title="toLabel(group.group.name)"
                        >
                            <template v-slot:prepend>
                                <v-progress-circular v-if="busyGroupUID === group.group.uid" indeterminate="disable-shrink" color="primary" size="20" class="mr-5"></v-progress-circular>
                                
                                <v-icon @click.stop="deselectGroup(group)" color="primary" v-else-if="groupSelected(group) === 'all'">mdi-check-circle-outline</v-icon>
                                <v-icon @click.stop="selectGroup(group)" v-else-if="groupSelected(group) === 'partial'" color="muted">mdi-circle-slice-8</v-icon>
                                <v-icon @click.stop="selectGroup(group)" v-else>mdi-circle-outline</v-icon>
                            </template>
                        </v-list-item>
                    </template>

                    <v-list-item 
                        v-for="(template, uid) in group.templates"
                        @click.stop="applyTemplate(template)"
                        :key="uid" 
                        :disabled="busy">
                        <template v-slot:prepend>
                            <v-progress-circular v-if="busyTemplateUID === template.uid" indeterminate="disable-shrink" color="primary" size="20" class="mr-5"></v-progress-circular>
                            <v-icon @click.stop="deselectTemplate(template.uid)" color="primary" v-else-if="templateSelected(template.uid)">mdi-check-circle-outline</v-icon>
                            <v-icon @click.stop="selectTemplate(template.uid)" v-else>mdi-circle-outline</v-icon>
                        </template>
                        <v-list-item-title>{{ template.name }}</v-list-item-title>
                        <v-list-item-subtitle>{{ template.description }}</v-list-item-subtitle>
                    </v-list-item>
                </v-list-group>
            </div>
            <v-divider></v-divider>

        </v-list>
    </div>
    <div v-else>
        <v-card density="compact">
            <v-card-text class="text-muted">
                <p>No templates available, or all viable templates have already been applied.</p>
            </v-card-text>
        </v-card>
    </div>
</template>

<script>
export default {
    name: "WorldStateManagerTemplateApplicator",
    components: {
    },
    data() {
        return {
            show: false,
            groupsOpen: [],
            busy: false,
            selectedTemplates: [],
            busyTemplateUID: null,
            busyGroupUID: null,
        }
    },
    props: {
        source: String,
        templates: Object,
        validateTemplate: Function,
        templateTypes: Array,
    },
    emits: [
        'apply-selected',
    ],
    inject: [
        'toLabel',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    computed: {
        viableTemplates() {
            let viable = [];

            for (let group of this.templates.managed.groups) {
                let templates = [];

                for (let templateId in group.templates) {
                    let template = group.templates[templateId];
                    if(this.validateTemplate(template)) {
                        templates.push(template);
                    }
                }

                if (templates.length > 0) {
                    viable.push({
                        group: group,
                        templates: templates
                    })
                }
            }
            viable.sort((a, b) => a.group.name.localeCompare(b.group.name));
            console.log("viable", viable)
            return viable;

        },
        templatesAvailable() {
            for (let templateType in this.templates.by_type) {
                for (let templateId in this.templates.by_type[templateType]) {
                    let template = this.templates.by_type[templateType][templateId];
                    if(this.validateTemplate(template)) {
                        return true;
                    }
                }
            }
            return false;
        },

    },
    methods: {

        selectGroup(group) {
            // adds all templates in group to selectedTemplates
            for (let templateId in group.templates) {
                let template = group.templates[templateId];
                if(!this.selectedTemplates.includes(template.uid)) {
                    this.selectedTemplates.push(template.uid);
                }
            }
        },

        deselectGroup(group) {
            // removes all templates in group from selectedTemplates
            for (let templateId in group.templates) {
                let template = group.templates[templateId];
                this.selectedTemplates = this.selectedTemplates.filter(selected => selected !== template.uid);
            }
        },

        groupSelected(group) {
            // returns "all" if all templates in group are selected
            // returns "partial" if some templates in group are selected
            // returns false if no templates in group are selected

            let allSelected = true;
            let anySelected = false;

            for (let templateId in group.templates) {
                let template = group.templates[templateId];
                if(!this.selectedTemplates.includes(template.uid)) {
                    allSelected = false;
                    continue;
                }
                anySelected = true;
            }
            return allSelected ? "all" : anySelected ? "partial" : false;
        },

        templateSelected(uid) {
            return this.selectedTemplates.includes(uid);
        },

        deselectTemplate(uid) {
            this.selectedTemplates = this.selectedTemplates.filter(selected => selected !== uid);
        },

        selectTemplate(uid) {
            if (this.selectedTemplates.includes(uid)) {
                this.selectedTemplates = this.selectedTemplates.filter(selected => selected !== uid);
            } else {
                this.selectedTemplates.push(uid);
            }
        },
        applyTemplate(template) {
            this.busy = true;
            this.$emit('apply-selected', [template.uid], () => {
                this.busy = false;
            });
        },

        applySelected() {
            this.busy = true;
            this.$emit('apply-selected', this.selectedTemplates, () => {
                this.busy = false;
            });
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager' || message.source !== this.source) {
                return;
            }  
            else if (message.action === 'template_applying') {
                console.log("template_applying", message.data.uid, message.data.group, {message})
                this.busyTemplateUID = message.data.uid;
                this.busyGroupUID = message.data.group;
            }
            else if (message.action === 'template_applied'){
                this.busyTemplateUID = null;
                this.busyGroupUID = null;
            }
            else if (message.action === 'templates_applied') {
                this.busyTemplateUID = null;
                this.busyGroupUID = null;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>