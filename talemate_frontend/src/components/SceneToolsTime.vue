<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-btn class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon variant="text">
                <v-icon>mdi-clock</v-icon>
            </v-btn>
        </template>
        <v-list density="compact">
            <v-list-subheader>Advance Time</v-list-subheader>

            <v-menu v-for="group in timeGroups" :key="group.label" open-on-hover location="end">
                <template v-slot:activator="{ props }">
                    <v-list-item v-bind="props" @click.stop :prepend-icon="group.icon" append-icon="mdi-chevron-right" density="compact">
                        <v-list-item-title>{{ group.label }}</v-list-item-title>
                    </v-list-item>
                </template>
                <v-list density="compact">
                    <v-list-item v-for="option in group.options" :key="option.value"
                        density="compact" @click="advanceTime(option.value)">
                        <v-list-item-title class="text-capitalize">{{ option.title }}</v-list-item-title>
                    </v-list-item>
                </v-list>
            </v-menu>

            <v-divider />
            <v-list-item density="compact" @click="openCustomTimeDialog">
                <v-list-item-title>Custom...</v-list-item-title>
            </v-list-item>
        </v-list>
    </v-menu>

    <!-- Custom Time Dialog -->
    <v-dialog v-model="customTimeDialog" max-width="400">
        <v-card>
            <v-card-title class="text-body-1">Advance Time</v-card-title>
            <v-card-text>
                <div class="d-flex align-center">
                    <v-number-input v-model="customTimeAmount" :min="1" label="Amount"
                        style="max-width: 180px" hide-details="auto" />
                    <v-select v-model="customTimeUnit" :items="customTimeUnits" label="Unit"
                        style="max-width: 180px" hide-details="auto" class="ml-2" />
                </div>
            </v-card-text>
            <v-card-actions>
                <v-spacer />
                <v-btn variant="text" @click="customTimeDialog = false">Cancel</v-btn>
                <v-btn color="primary" @click="submitCustomTime">Advance</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import { amountUnitToSeconds } from '@/utils/time';

export default {
    name: "SceneToolsTime",
    props: {
        disabled: Boolean,
    },
    inject: ['getWebsocket'],
    data() {
        return {
            customTimeDialog: false,
            customTimeAmount: 1,
            customTimeUnit: 'hours',
            customTimeUnits: ['minutes', 'hours', 'days', 'weeks', 'months', 'years'],
            timeGroups: [
                {
                    label: "Minutes",
                    icon: "mdi-timer-sand",
                    options: [
                        {"value": amountUnitToSeconds(5, 'minutes'), "title": "5 minutes"},
                        {"value": amountUnitToSeconds(15, 'minutes'), "title": "15 minutes"},
                        {"value": amountUnitToSeconds(30, 'minutes'), "title": "30 minutes"},
                    ],
                },
                {
                    label: "Hours",
                    icon: "mdi-clock-outline",
                    options: [
                        {"value": amountUnitToSeconds(1, 'hours'), "title": "1 hour"},
                        {"value": amountUnitToSeconds(2, 'hours'), "title": "2 hours"},
                        {"value": amountUnitToSeconds(4, 'hours'), "title": "4 hours"},
                        {"value": amountUnitToSeconds(8, 'hours'), "title": "8 hours"},
                        {"value": amountUnitToSeconds(12, 'hours'), "title": "12 hours"},
                    ],
                },
                {
                    label: "Days",
                    icon: "mdi-weather-sunny",
                    options: [
                        {"value": amountUnitToSeconds(1, 'days'), "title": "1 day"},
                        {"value": amountUnitToSeconds(2, 'days'), "title": "2 days"},
                        {"value": amountUnitToSeconds(3, 'days'), "title": "3 days"},
                    ],
                },
                {
                    label: "Weeks",
                    icon: "mdi-calendar-week",
                    options: [
                        {"value": amountUnitToSeconds(1, 'weeks'), "title": "1 week"},
                        {"value": amountUnitToSeconds(2, 'weeks'), "title": "2 weeks"},
                    ],
                },
                {
                    label: "Months",
                    icon: "mdi-calendar-month",
                    options: [
                        {"value": amountUnitToSeconds(1, 'months'), "title": "1 month"},
                        {"value": amountUnitToSeconds(3, 'months'), "title": "3 months"},
                        {"value": amountUnitToSeconds(6, 'months'), "title": "6 months"},
                    ],
                },
                {
                    label: "Years",
                    icon: "mdi-calendar-multiple",
                    options: [
                        {"value": amountUnitToSeconds(1, 'years'), "title": "1 year"},
                        {"value": amountUnitToSeconds(2, 'years'), "title": "2 years"},
                        {"value": amountUnitToSeconds(3, 'years'), "title": "3 years"},
                        {"value": amountUnitToSeconds(5, 'years'), "title": "5 years"},
                        {"value": amountUnitToSeconds(10, 'years'), "title": "10 years"},
                    ],
                },
            ],
        }
    },
    methods: {
        advanceTime(duration) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_agent',
                action: 'advance_time',
                duration: duration,
            }));
        },

        openCustomTimeDialog() {
            this.customTimeAmount = 1;
            this.customTimeUnit = 'hours';
            this.customTimeDialog = true;
        },

        submitCustomTime() {
            this.advanceTime(amountUnitToSeconds(this.customTimeAmount, this.customTimeUnit));
            this.customTimeDialog = false;
        },
    },
}
</script>
