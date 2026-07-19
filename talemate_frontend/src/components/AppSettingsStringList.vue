<template>
    <AppSettingsPageHeader :title="title" :icon="icon">
        <slot></slot>
    </AppSettingsPageHeader>
    <v-row>
        <v-col cols="12">
            <v-list density="compact">
                <v-list-item v-for="(value, index) in list" :key="index">
                    <v-list-item-title><v-icon color="red-darken-1" class="mr-2" @click="remove(index)">mdi-close-box-outline</v-icon>{{ value }}</v-list-item-title>
                </v-list-item>
            </v-list>
            <v-divider></v-divider>
            <v-text-field v-model="input" :label="inputLabel"
                @keyup.enter="add"></v-text-field>
        </v-col>
    </v-row>
</template>

<script>
import AppSettingsPageHeader from './AppSettingsPageHeader.vue';

export default {
    name: 'AppSettingsStringList',
    components: {
        AppSettingsPageHeader,
    },
    props: {
        title: String,
        icon: String,
        inputLabel: String,
        list: Array,
    },
    emits: [
        'update:list',
    ],
    data() {
        return {
            input: '',
        }
    },
    methods: {
        add() {
            const value = (this.input || '').trim();
            if (!value) return;
            this.$emit('update:list', [...(this.list || []), value]);
            this.input = '';
        },
        remove(index) {
            const updated = [...(this.list || [])];
            updated.splice(index, 1);
            this.$emit('update:list', updated);
        },
    },
}
</script>
