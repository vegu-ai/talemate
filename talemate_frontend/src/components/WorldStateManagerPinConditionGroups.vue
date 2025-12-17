<template>
    <div>
        <v-alert v-if="readonly" variant="text" color="grey" icon="mdi-lock">
            This pin is controlled by game state. It cannot be manually toggled and does not decay.
        </v-alert>

        <v-card>
            <v-card-actions class="px-0">
                <v-btn variant="text" color="primary" prepend-icon="mdi-plus" @click.stop="addGroup" :disabled="readonly">
                    Add condition group
                </v-btn>
                <v-spacer></v-spacer>
                <div class="text-caption text-grey" v-if="groups.length > 0">
                    A pin matches if any group matches. Inside a group, conditions combine with the group operator.
                </div>
            </v-card-actions>

            <v-alert v-if="groups.length === 0" variant="outlined" color="muted">
                <div class="text-body-2">
                    <strong>No game-state conditions set.</strong>
                    <br><br>
                    Game-state conditions allow you to automatically pin/unpin entries based on game state variables. 
                    Add condition groups where each group contains one or more conditions that check game state paths (e.g., "quest/stage", "character/mood").
                    <br><br>
                    • A pin matches if <strong>any</strong> group matches (groups are combined with OR)
                    <br>
                    • Inside a group, conditions combine with the group operator (AND or OR)
                    <br>
                    • Use operators like ==, !=, >, <, in, is_true, etc. to compare values
                    <br><br>
                    Click "Add condition group" above to get started. You can view and edit game state variables in the Game State Editor.
                </div>
            </v-alert>

            <div v-for="(group, groupIdx) in groups" :key="groupIdx">
                <v-card variant="outlined" color="muted" class="mb-3">
                    <v-card-title class="py-2">
                        <div class="d-flex align-center" style="width: 100%; gap: 8px;">
                            <div class="text-subtitle-2">Group {{ groupIdx + 1 }}</div>
                            <v-spacer></v-spacer>
                            <v-select
                                hide-details
                                density="compact"
                                label="Group operator"
                                :items="groupOperatorItems"
                                v-model="group.operator"
                                style="max-width: 170px;"
                                :disabled="readonly"
                                @blur="emitChange"
                            />
                            <v-btn variant="text" color="primary" prepend-icon="mdi-plus" :disabled="readonly" @click.stop="addCondition(groupIdx)">
                                Add condition
                            </v-btn>
                            <v-btn variant="text" color="delete" prepend-icon="mdi-close-box-outline" :disabled="readonly" @click.stop="removeGroup(groupIdx)">
                                Remove group
                            </v-btn>
                        </div>
                    </v-card-title>

                    <v-divider></v-divider>

                    <v-card-text>
                        <v-alert v-if="!group.conditions || group.conditions.length === 0" variant="text" color="grey" icon="mdi-alert-circle-outline">
                            Empty groups never match. Add at least one condition.
                        </v-alert>

                        <div v-for="(cond, condIdx) in group.conditions" :key="condIdx" class="mb-2">
                            <v-row dense>
                                <v-col cols="12" md="5">
                                    <v-combobox
                                        hide-details
                                        density="compact"
                                        label="Path"
                                        v-model="cond.path"
                                        :items="gameStatePaths"
                                        placeholder="e.g. quest/stage"
                                        :disabled="readonly"
                                        @blur="emitChange"
                                        @update:model-value="emitChange"
                                    />
                                </v-col>
                                <v-col cols="12" md="3">
                                    <v-select
                                        hide-details
                                        density="compact"
                                        label="Operator"
                                        :items="operatorItems"
                                        v-model="cond.operator"
                                        :disabled="readonly"
                                        @update:model-value="onOperatorChanged(groupIdx, condIdx)"
                                    />
                                </v-col>
                                <v-col cols="12" md="3">
                                    <v-text-field
                                        v-if="!operatorTakesNoValue(cond.operator)"
                                        hide-details
                                        density="compact"
                                        label="Value"
                                        v-model="cond.value"
                                        placeholder="number or string"
                                        :disabled="readonly"
                                        @blur="emitChange"
                                    />
                                    <v-text-field
                                        v-else
                                        hide-details
                                        density="compact"
                                        label="Value"
                                        model-value=""
                                        placeholder="(no value)"
                                        disabled
                                    />
                                </v-col>
                                <v-col cols="12" md="1" class="d-flex align-center justify-end">
                                    <v-btn
                                        variant="text"
                                        color="delete"
                                        icon="mdi-close-circle-outline"
                                        size="small"
                                        :disabled="readonly"
                                        @click.stop="removeCondition(groupIdx, condIdx)"
                                    />
                                </v-col>
                            </v-row>
                        </div>
                    </v-card-text>
                </v-card>
                <div v-if="groupIdx < groups.length - 1" class="text-center my-2">
                    <span class="text-subtitle-1 font-weight-bold text-grey">OR</span>
                </div>
            </div>
        </v-card>
    </div>
</template>

<script>
import { extractGameStatePaths } from '@/utils/gameStatePaths.js';

export default {
    name: 'WorldStateManagerPinConditionGroups',
    props: {
        modelValue: {
            type: Array,
            default: () => ([]),
        },
        readonly: {
            type: Boolean,
            default: false,
        },
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    data() {
        return {
            groups: [],
            gameStatePaths: [],
            groupOperatorItems: [
                { title: 'AND', value: 'and' },
                { title: 'OR', value: 'or' },
            ],
            operatorItems: [
                { title: '==', value: '==' },
                { title: '!=', value: '!=' },
                { title: '>', value: '>' },
                { title: '<', value: '<' },
                { title: '>=', value: '>=' },
                { title: '<=', value: '<=' },
                { title: 'in', value: 'in' },
                { title: 'not_in', value: 'not_in' },
                { title: 'is_true', value: 'is_true' },
                { title: 'is_false', value: 'is_false' },
                { title: 'is_null', value: 'is_null' },
                { title: 'is_not_null', value: 'is_not_null' },
            ],
        }
    },
    watch: {
        modelValue: {
            immediate: true,
            deep: true,
            handler(value) {
                this.groups = Array.isArray(value) ? JSON.parse(JSON.stringify(value)) : [];
            }
        },
    },
    methods: {
        operatorTakesNoValue(op) {
            return ['is_true', 'is_false', 'is_null', 'is not null', 'is_not_null'].includes(op);
        },
        emitChange() {
            this.$emit('update:modelValue', JSON.parse(JSON.stringify(this.groups)));
        },
        addGroup() {
            this.groups.push({
                operator: 'and',
                conditions: [
                    { path: '', operator: '==', value: '' },
                ],
            });
            this.emitChange();
        },
        removeGroup(idx) {
            this.groups.splice(idx, 1);
            this.emitChange();
        },
        addCondition(groupIdx) {
            this.groups[groupIdx].conditions.push({ path: '', operator: '==', value: '' });
            this.emitChange();
        },
        removeCondition(groupIdx, condIdx) {
            this.groups[groupIdx].conditions.splice(condIdx, 1);
            this.emitChange();
        },
        onOperatorChanged(groupIdx, condIdx) {
            const cond = this.groups[groupIdx].conditions[condIdx];
            if (this.operatorTakesNoValue(cond.operator)) {
                cond.value = null;
            } else if (cond.value === null || cond.value === undefined) {
                cond.value = '';
            }
            this.emitChange();
        },
        refreshGameStatePaths() {
            this.getWebsocket().send(
                JSON.stringify({ type: 'devtools', action: 'get_game_state' })
            );
        },
        handleMessage(message) {
            if (message.type !== 'devtools') return;
            if (message.action === 'game_state' || message.action === 'game_state_updated') {
                const variables = message.data?.variables || {};
                const paths = extractGameStatePaths(variables, '', { includeContainers: false });
                // Sort and remove duplicates
                this.gameStatePaths = [...new Set(paths)].sort();
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.refreshGameStatePaths();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>
