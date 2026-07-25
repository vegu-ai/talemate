<template>
    <v-card variant="tonal">
        <v-card-text>
            <div v-if="envVariableNames.length === 0" class="text-grey text-body-2 mb-4">
                No environment variables defined yet — add one below.
            </div>
            <v-row v-for="name in envVariableNames" :key="name" dense>
                <v-col cols="5">
                    <v-text-field :model-value="name" label="Name" readonly density="compact" hide-details></v-text-field>
                </v-col>
                <v-col cols="6">
                    <v-text-field type="password" v-model="config.env[name]" label="Value" density="compact" hide-details></v-text-field>
                </v-col>
                <v-col cols="1" class="d-flex align-center">
                    <v-btn icon="mdi-close-circle-outline" variant="text" color="delete" size="small" @click="envVariableRemove(name)"></v-btn>
                </v-col>
            </v-row>
            <v-divider v-if="envVariableNames.length > 0" class="my-4"></v-divider>
            <v-row dense>
                <v-col cols="5">
                    <v-text-field v-model="env_variable_name_input" label="Name" density="compact"
                        :rules="[validateEnvVariableName]" placeholder="MY_API_KEY"
                        @keyup.enter="envVariableAdd"></v-text-field>
                </v-col>
                <v-col cols="6">
                    <v-text-field type="password" v-model="env_variable_value_input" label="Value" density="compact"
                        @keyup.enter="envVariableAdd"></v-text-field>
                </v-col>
                <v-col cols="1" class="d-flex align-center">
                    <v-btn icon="mdi-plus-circle-outline" variant="text" color="primary" size="small"
                        :disabled="!envVariableAddValid" @click="envVariableAdd"></v-btn>
                </v-col>
            </v-row>
        </v-card-text>
    </v-card>
</template>

<script>
export default {
    name: 'AppSettingsEnvVariables',
    props: {
        config: Object,
    },
    data() {
        return {
            env_variable_name_input: '',
            env_variable_value_input: '',
        }
    },
    computed: {
        envVariableNames() {
            return Object.keys(this.config?.env || {}).sort();
        },
        envVariableAddValid() {
            return this.validateEnvVariableName(this.env_variable_name_input) === true
                && this.env_variable_name_input.trim() !== ''
                && this.env_variable_value_input !== '';
        },
    },
    methods: {
        validateEnvVariableName(value) {
            const name = (value || '').trim();
            if (!name) return true;
            if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) {
                return 'Letters, digits and underscores only; must not start with a digit';
            }
            if (this.config?.env && name in this.config.env) {
                return 'Already exists — edit its row above';
            }
            return true;
        },
        envVariableAdd() {
            if (!this.envVariableAddValid) return;
            const name = this.env_variable_name_input.trim();
            if (!this.config.env) {
                this.config.env = {};
            }
            this.config.env[name] = this.env_variable_value_input;
            this.env_variable_name_input = '';
            this.env_variable_value_input = '';
        },
        envVariableRemove(name) {
            delete this.config.env[name];
        },
    },
}
</script>
