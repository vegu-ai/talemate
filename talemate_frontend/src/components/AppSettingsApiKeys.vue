<template>
    <AppSettingsPageHeader title="API Keys" icon="mdi-key-variant">
        API keys and access tokens for third party services. Only fill in the services you use.
    </AppSettingsPageHeader>
    <v-card v-for="provider in providers" :key="provider.id" class="mb-3" variant="tonal" :data-setting-anchor="provider.id">
        <v-card-title class="text-subtitle-1">
            <v-icon start size="small">{{ provider.icon || 'mdi-api' }}</v-icon>
            {{ provider.title }}
        </v-card-title>
        <v-card-text>
            <div class="text-grey text-body-2 mb-2">
                <p v-if="provider.description" class="mb-1">{{ provider.description }}</p>
                <template v-if="provider.id === 'google_api'">
                    <p class="mb-2"><strong>Option&nbsp;1 – API&nbsp;Key&nbsp;(recommended)</strong></p>
                    <p class="mb-1">Create a Google API key at <a href="https://aistudio.google.com/apikey" target="_blank">aistudio.google.com/apikey</a> and paste it in the field below. This is the quickest way to start using Gemini models.</p>
                    <p class="mb-2 mt-3"><strong>Option&nbsp;2 – Vertex&nbsp;AI service&nbsp;account&nbsp;(advanced)</strong></p>
                    <p class="mb-0">If you prefer using a full Google Cloud project, follow the setup guide <a href="https://cloud.google.com/vertex-ai/docs/start/client-libraries" target="_blank">here</a> to generate a service-account JSON credential file, then complete the legacy fields below.</p>
                    <p class="text-caption mt-1 text-muted">
                        If both are setup, the API key will be used.
                    </p>
                </template>
                <template v-else>
                    Get your key from <a :href="provider.url" target="_blank">{{ provider.urlLabel || provider.url }}</a> <span v-if="provider.urlNote" class="text-caption">{{ provider.urlNote }}</span>
                </template>
            </div>
            <v-text-field type="password" v-model="config[provider.section].api_key"
                :label="provider.fieldLabel" density="compact" hide-details></v-text-field>
            <template v-if="provider.id === 'google_api'">
                <v-text-field v-model="config.google.gcloud_credentials_path" class="mt-3"
                    label="Google Cloud Credentials Path" density="compact" messages="Path to the service-account JSON credentials file on the machine running the Talemate backend."></v-text-field>
                <v-combobox v-model="config.google.gcloud_location" class="mt-3"
                    label="Google Cloud Location" density="compact" :items="googleCloudLocations" messages="Pick something close to you" :return-object="false"></v-combobox>
            </template>
        </v-card-text>
    </v-card>
</template>

<script>
import AppSettingsPageHeader from './AppSettingsPageHeader.vue';
import { API_PROVIDERS } from '../utils/appSettingsRegistry.js';

export default {
    name: 'AppSettingsApiKeys',
    components: {
        AppSettingsPageHeader,
    },
    props: {
        config: Object,
    },
    data() {
        return {
            providers: API_PROVIDERS,
            googleCloudLocations: [
                {"value": 'us-central1', "title": 'US Central - Iowa'},
                {"value": 'us-west4', "title": 'US West 4 - Las Vegas'},
                {"value": 'us-east1', "title": 'US East 1 - South Carolina'},
                {"value": 'us-east4', "title": 'US East 4 - Northern Virginia'},
                {"value": 'us-west1', "title": 'US West 1 - Oregon'},
                {"value": 'northamerica-northeast1', "title": 'North America Northeast 1 - Montreal'},
                {"value": 'southamerica-east1', "title": 'South America East 1 - Sao Paulo'},
                {"value": 'europe-west1', "title": 'Europe West 1 - Belgium'},
                {"value": 'europe-north1', "title": 'Europe North 1 - Finland'},
                {"value": 'europe-west3', "title": 'Europe West 3 - Frankfurt'},
                {"value": 'europe-west2', "title": 'Europe West 2 - London'},
                {"value": 'europe-southwest1', "title": 'Europe Southwest 1 - Zurich'},
                {"value": 'europe-west8', "title": 'Europe West 8 - Netherlands'},
                {"value": 'europe-west4', "title": 'Europe West 4 - London'},
                {"value": 'europe-west9', "title": 'Europe West 9 - Stockholm'},
                {"value": 'europe-central2', "title": 'Europe Central 2 - Warsaw'},
                {"value": 'europe-west6', "title": 'Europe West 6 - Zurich'},
                {"value": 'asia-east1', "title": 'Asia East 1 - Taiwan'},
                {"value": 'asia-east2', "title": 'Asia East 2 - Hong Kong'},
                {"value": 'asia-south1', "title": 'Asia South 1 - Mumbai'},
                {"value": 'asia-northeast1', "title": 'Asia Northeast 1 - Tokyo'},
                {"value": 'asia-northeast3', "title": 'Asia Northeast 3 - Seoul'},
                {"value": 'asia-southeast1', "title": 'Asia Southeast 1 - Singapore'},
                {"value": 'asia-southeast2', "title": 'Asia Southeast 2 - Jakarta'},
                {"value": 'australia-southeast1', "title": 'Australia Southeast 1 - Sydney'},
                {"value": 'australia-southeast2', "title": 'Australia Southeast 2 - Melbourne'},
                {"value": 'me-west1', "title": 'Middle East West 1 - Dammam'},
                {"value": 'asia-northeast2', "title": 'Asia Northeast 2 - Osaka'},
            ].sort((a, b) => a.title.localeCompare(b.title)),
        }
    },
}
</script>
