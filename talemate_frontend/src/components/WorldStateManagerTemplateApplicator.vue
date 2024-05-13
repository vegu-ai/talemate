<template>
    <div v-if="templatesAvailable">
        <v-list density="compact" slim v-model:opened="groupsOpen">
            <!--
            <v-list-item density="compact"  class="text-primary"
                @click.stop="show = !show"
                prepend-icon="mdi-cube-scan" color="info">
                <v-list-item-title class="text-primary">
                    Templates
                    <v-progress-circular class="ml-1 mr-3" size="14"
                        indeterminate="disable-shrink" color="primary"
                        v-if="busy"></v-progress-circular>
                </v-list-item-title>
            </v-list-item>
            -->
            <div>
                <v-list-group fluid v-for="(group, index) in viableTemplates" :key="index" :value="group.group.uid">
                    <template v-slot:activator="{ props }">
                        <v-list-item v-bind="props" class="text-caption text-muted"
                            :title="toLabel(group.group.name)"
                        ></v-list-item>
                    </template>
                    <v-list-item v-if="group.templates.length > 0" prepend-icon="mdi-expand-all" @click.stop="applyGroup(group.group)">
                        <v-list-item-title>Apply all</v-list-item-title>
                        <v-list-item-subtitle>Apply all items in this group.</v-list-item-subtitle>
                    </v-list-item>
                    <v-list-item 
                        v-for="(template, uid) in group.templates"
                        @click.stop="applyTemplate(template)"
                        :key="uid" 
                        prepend-icon="mdi-cube-scan"
                        :disabled="busy">
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
                <p>No templates available.</p>
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
        }
    },
    props: {
        templates: Object,
        validateTemplate: Function,
        templateTypes: Array,
    },
    emits: [
        'apply-template',
        'apply-group',
    ],
    inject: [
        'toLabel',
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
        applyTemplate(template) {
            this.busy = true;
            this.$emit('apply-template', template, () => {
                this.busy = false;
            });
        },

        applyGroup(group) {
            this.busy = true;
            this.$emit('apply-group', group, () => {
                this.busy = false;
            });
        },

    }
}
</script>