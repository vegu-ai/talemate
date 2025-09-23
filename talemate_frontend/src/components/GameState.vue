<template>
    <div>
        

        <v-card variant="text">
            <v-card-text>
                <v-row>
                    <v-col cols="12" sm="12" md="12" lg="12" xl="8" xxl="6">
                        <div class="d-flex align-center mb-2">
                            <v-menu v-if="loaded && root" class="mr-2">
                                <template #activator="{ props }">
                                    <v-btn v-bind="props" size="small" color="primary" variant="text" class="mr-2" prepend-icon="mdi-plus">Add</v-btn>
                                </template>
                                <v-list density="compact">
                                    <template v-for="(action, i) in objectAddActions(root)" :key="'root-add-'+i">
                                        <v-divider v-if="action.divider"></v-divider>
                                        <v-list-item v-else :title="action.title" @click="action.onClick"></v-list-item>
                                    </template>
                                </v-list>
                            </v-menu>
                            <v-btn size="small" :disabled="busy" color="primary" variant="text" class="mr-2" prepend-icon="mdi-refresh" @click.stop="refresh">Refresh</v-btn>
                            <v-btn size="small" :disabled="busy" color="success" variant="text" prepend-icon="mdi-content-save" @click.stop="commitChanges">Apply</v-btn>
                            <v-spacer></v-spacer>
                        </div>

                        <v-divider class="mb-2"></v-divider>

                        <v-alert v-if="!loaded" color="muted" density="compact" variant="text">No game state loaded.</v-alert>

                        <div v-else-if="root && (!root.children || root.children.length === 0)" class="d-flex align-center">
                            <v-alert color="muted" density="compact" variant="tonal" class="flex-grow-1 mr-2">Gamestate is currently empty</v-alert>
                            <v-menu>
                                <template #activator="{ props }">
                                    <v-btn v-bind="props" color="primary" variant="tonal" prepend-icon="mdi-plus">Add</v-btn>
                                </template>
                                <v-list density="compact">
                                    <template v-for="(action, i) in objectAddActions(root)" :key="'empty-add-'+i">
                                        <v-divider v-if="action.divider"></v-divider>
                                        <v-list-item v-else :title="action.title" @click="action.onClick"></v-list-item>
                                    </template>
                                </v-list>
                            </v-menu>
                        </div>

                        <v-treeview
                            v-else
                            :items="treeItems"
                            item-value="id"
                            color="muted"
                            activatable
                            open-on-click
                            hoverable
                            v-model:opened="open"
                            density="compact"
                            class="gs-tree"
                        >
                            <template #title="{ item }">
                                <div class="gs-title d-flex align-center">
                                    <v-chip label size="x-small" class="mr-1" :color="chipColor(slotNode(item))" variant="tonal">{{ chipLabel(slotNode(item)) }}</v-chip>
                                    <template v-if="slotNode(item).kind === 'object'">
                                        <template v-if="slotNode(item).parentKind === 'object'">
                                            <template v-if="isEditing(slotNode(item).id, 'key')">
                                                <v-text-field
                                                    v-model="slotNode(item).key"
                                            @keydown.enter.prevent="onKeyEnter(slotNode(item))"
                                                    @update:modelValue="(v) => slotNode(item).label = v"
                                                    :ref="el => setKeyRef(slotNode(item).id, el)"
                                                    @blur="stopEdit()"
                                                    density="compact"
                                                    variant="outlined"
                                                    hide-details
                                                    class="mr-1 py-0 gs-maxw-160"
                                                    placeholder="key"
                                                ></v-text-field>
                                            </template>
                                            <template v-else>
                                                <span class="text-subtitle-2 mr-1" @dblclick.stop="startEdit(slotNode(item).id, 'key')">{{ slotNode(item).key }}</span>
                                            </template>
                                        </template>
                                        <template v-else>
                                            <span class="text-subtitle-2">{{ slotNode(item).label }}</span>
                                        </template>
                                    </template>
                                    <template v-else-if="slotNode(item).kind === 'array'">
                                        <template v-if="slotNode(item).parentKind === 'object'">
                                            <template v-if="isEditing(slotNode(item).id, 'key')">
                                                <v-text-field
                                                    v-model="slotNode(item).key"
                                            @keydown.enter.prevent="onKeyEnter(slotNode(item))"
                                                    @update:modelValue="(v) => slotNode(item).label = v"
                                                    @blur="stopEdit()"
                                                    density="compact"
                                                    variant="outlined"
                                                    hide-details
                                                    class="mr-1 py-0 gs-maxw-160"
                                                    placeholder="key"
                                                ></v-text-field>
                                            </template>
                                            <template v-else>
                                                <span class="text-subtitle-2 mr-1" @dblclick.stop="startEdit(slotNode(item).id, 'key')">{{ slotNode(item).key }}</span>
                                            </template>
                                        </template>
                                        <template v-else>
                                            <span class="text-subtitle-2">{{ slotNode(item).label }}</span>
                                        </template>
                                    </template>
                                    <template v-else>
                                        <!-- Order: TYPE, KEY, ":", VALUE -->
                                        <!-- Type -->
                                        <template v-if="isEditing(slotNode(item).id, 'type')">
                                            <v-select
                                                v-model="slotNode(item).valueType"
                                                :items="valueTypes"
                                                @update:modelValue="() => onTypeChange(slotNode(item))"
                                                density="compact"
                                                hide-details
                                                variant="outlined"
                                                class="mr-1 py-0 gs-maxw-140"
                                                @keydown.enter.prevent="stopEdit()"
                                                @blur="stopEdit()"
                                            ></v-select>
                                        </template>
                                        <template v-else>
                                            <v-chip size="x-small" class="mr-1" label color="highlight5" variant="tonal" @dblclick.stop="startEdit(slotNode(item).id, 'type')" @click.stop="startEdit(slotNode(item).id, 'type')">{{ String(slotNode(item).valueType || detectType(slotNode(item).value)).toUpperCase() }}</v-chip>
                                        </template>

                                        <!-- Key (chip if not editing) -->
                                        <template v-if="slotNode(item).parentKind === 'object'">
                                            <template v-if="isEditing(slotNode(item).id, 'key')">
                                                <v-text-field
                                                    v-model="slotNode(item).key"
                                                    @keydown.enter.prevent="onKeyEnter(slotNode(item))"
                                                    :ref="el => setKeyRef(slotNode(item).id, el)"
                                                    @blur="stopEdit()"
                                                    density="compact"
                                                    variant="outlined"
                                                    hide-details
                                                    class="mr-3 py-0 gs-maxw-160"
                                                    placeholder="key"
                                                ></v-text-field>:
                                            </template>
                                            <template v-else>
                                                <v-chip size="medium" class="mr-3" label color="white" variant="text" @dblclick.stop="startEdit(slotNode(item).id, 'key')" @click.stop="startEdit(slotNode(item).id, 'key')">{{ slotNode(item).key }}:</v-chip>
                                            </template>
                                        </template>

                                        <!-- Value -->
                                        <template v-if="slotNode(item).valueType === 'bool'">
                                            <v-chip
                                                size="small"
                                                label
                                                :color="slotNode(item).value ? 'success' : 'muted'"
                                                variant="tonal"
                                                @dblclick.stop="toggleBoolValue(slotNode(item))"
                                                @click.stop="toggleBoolValue(slotNode(item))"
                                            >{{ slotNode(item).value ? 'true' : 'false' }}</v-chip>
                                        </template>
                                        <template v-else>
                                            <template v-if="isEditing(slotNode(item).id, 'value')">
                                                <v-text-field
                                                    :model-value="itemInputValue(slotNode(item))"
                                                    @update:modelValue="(v) => setItemInputValue(slotNode(item), v)"
                                                    :type="inputType(slotNode(item).valueType)"
                                                    @keydown.enter.prevent="stopEdit()"
                                                    :ref="el => setValueRef(slotNode(item).id, el)"
                                                    @blur="stopEdit()"
                                                    density="compact"
                                                    variant="outlined"
                                                    hide-details
                                                    placeholder="value"
                                                    class="py-0 flex-grow-1 gs-minw-0"
                                                ></v-text-field>
                                            </template>
                                            <template v-else>
                                                <span class="text-body-2 text-muted gs-value-ellipsis" @dblclick.stop="startEdit(slotNode(item).id, 'value')" @click.stop="startEdit(slotNode(item).id, 'value')">{{ displayValue(slotNode(item)) }}</span>
                                            </template>
                                        </template>
                                    </template>
                                </div>
                            </template>
                            <template #append="{ item }">
                                <div class="d-flex align-center justify-end gs-w-100">
                                    <template v-if="slotNode(item).kind === 'object'">
                                        <v-menu>
                                            <template #activator="{ props }">
                                                <v-btn size="small" v-bind="props" variant="text" color="primary" prepend-icon="mdi-plus">Add</v-btn>
                                            </template>
                                            <v-list density="compact">
                                                <template v-for="(action, i) in objectAddActions(slotNode(item))" :key="'obj-add-'+slotNode(item).id+'-'+i">
                                                    <v-divider v-if="action.divider"></v-divider>
                                                    <v-list-item v-else :title="action.title" @click="action.onClick"></v-list-item>
                                                </template>
                                            </v-list>
                                        </v-menu>
                                    </template>

                                    <template v-else-if="slotNode(item).kind === 'array'">
                                        <v-menu>
                                            <template #activator="{ props }">
                                                <v-btn size="small" v-bind="props" variant="text" color="primary" prepend-icon="mdi-plus">Add</v-btn>
                                            </template>
                                            <v-list density="compact">
                                                <template v-for="(action, i) in arrayAddActions(slotNode(item))" :key="'arr-add-'+slotNode(item).id+'-'+i">
                                                    <v-divider v-if="action.divider"></v-divider>
                                                    <v-list-item v-else :title="action.title" @click="action.onClick"></v-list-item>
                                                </template>
                                            </v-list>
                                        </v-menu>
                                    </template>

                                    <confirm-action-inline
                                        class="ml-2"
                                        action-label="Delete"
                                        confirm-label="Delete"
                                        icon="mdi-close-circle-outline"
                                        color="delete"
                                        density="compact"
                                        @confirm="removeNode(slotNode(item))"
                                    />
                                </div>
                            </template>
                        </v-treeview>
                    </v-col>
                </v-row>
            </v-card-text>
        </v-card>
    </div>
    
</template>

<script>

import ConfirmActionInline from './ConfirmActionInline.vue';

let nextId = 1;

function newId() {
    return nextId++;
}

export default {
    name: 'GameState',
    components: {
        ConfirmActionInline,
    },
    props: {
        isVisible: Boolean,
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    data() {
        return {
            busy: false,
            loaded: false,
            open: [],
            openPaths: [],
            root: null,
            treeItems: [],
            keyRefs: {},
            valueRefs: {},
            valueTypes: [
                { title: 'String', value: 'str' },
                { title: 'Integer', value: 'int' },
                { title: 'Float', value: 'float' },
                { title: 'Boolean', value: 'bool' },
            ],
            editState: { id: null, field: null },
        };
    },
    watch: {
        isVisible(visible) {
            if (visible) {
                this.refresh();
            }
        },
    },
    methods: {
        objectAddActions(target) {
            return [
                { title: 'String', onClick: () => this.addObjectValue(target, 'str') },
                { title: 'Integer', onClick: () => this.addObjectValue(target, 'int') },
                { title: 'Float', onClick: () => this.addObjectValue(target, 'float') },
                { title: 'Boolean', onClick: () => this.addObjectValue(target, 'bool') },
                { divider: true },
                { title: 'Object', onClick: () => this.addObjectObject(target) },
                { title: 'Array', onClick: () => this.addObjectArray(target) },
            ];
        },
        arrayAddActions(target) {
            return [
                { title: 'String', onClick: () => this.addArrayValue(target, 'str') },
                { title: 'Integer', onClick: () => this.addArrayValue(target, 'int') },
                { title: 'Float', onClick: () => this.addArrayValue(target, 'float') },
                { title: 'Boolean', onClick: () => this.addArrayValue(target, 'bool') },
                { divider: true },
                { title: 'Object', onClick: () => this.addArrayObject(target) },
                { title: 'Array', onClick: () => this.addArrayArray(target) },
            ];
        },
        slotNode(slotItem) {
            // Vuetify v-treeview passes the raw item under slot param depending on version
            // Prefer raw if present, else the object itself
            return slotItem && (slotItem.raw || slotItem);
        },
        chipLabel(node) {
            if (!node) return 'V';
            return node.kind === 'object' ? 'O' : (node.kind === 'array' ? 'A' : 'V');
        },
        chipColor(node) {
            if (!node) return 'muted';
            // Use themed colors from vuetify.js
            if (node.kind === 'object') return 'highlight2';
            if (node.kind === 'array') return 'highlight3';
            return 'highlight1';
        },
        isEditing(id, field) {
            return this.editState.id === id && this.editState.field === field;
        },
        startEdit(id, field) {
            this.editState = { id, field };
            // after setting edit state, focus relevant element next tick
            this.$nextTick(() => {
                try {
                    if (field === 'key') {
                        const el = this.keyRefs[id]?.$el?.querySelector('input') || this.keyRefs[id]?.$el;
                        if (el) { el.focus(); el.select && el.select(); }
                    } else if (field === 'value') {
                        const el = this.valueRefs[id]?.$el?.querySelector('input') || this.valueRefs[id]?.$el;
                        if (el) { el.focus(); el.select && el.select(); }
                    }
                } catch(e) {}
            });
        },
        stopEdit() {
            this.editState = { id: null, field: null };
        },
        onTypeChange(node) {
            // When type changes, ensure value is sensible
            if (node.valueType === 'bool') {
                node.value = !!node.value;
            } else if (node.valueType === 'int') {
                node.value = parseInt(node.value || 0, 10) || 0;
            } else if (node.valueType === 'float') {
                node.value = parseFloat(node.value || 0) || 0.0;
            } else {
                node.value = node.value == null ? '' : String(node.value);
            }
        },
        // Preserve expansion state using key paths
        collectOpenPaths() {
            const acc = [];
            const root = this.root;
            if (!root) return acc;
            const walk = (node, path) => {
                if (this.open.includes(node.id)) {
                    acc.push(path);
                }
                for (const child of node.children || []) {
                    walk(child, `${path}.${child.key}`);
                }
            };
            for (const child of root.children || []) {
                walk(child, `${root.label}.${child.key}`);
            }
            return acc;
        },
        restoreOpened(root, paths) {
            const opened = [];
            const pathSet = new Set(paths || []);
            const walk = (node, path) => {
                if (pathSet.has(path)) {
                    opened.push(node.id);
                }
                for (const child of node.children || []) {
                    walk(child, `${path}.${child.key}`);
                }
            };
            for (const child of root.children || []) {
                walk(child, `${root.label}.${child.key}`);
            }
            return opened;
        },
        setKeyRef(id, el) {
            if (el) this.keyRefs[id] = el;
        },
        setValueRef(id, el) {
            if (el) this.valueRefs[id] = el;
        },
        refresh() {
            if (this.loaded) {
                this.openPaths = this.collectOpenPaths();
            }
            this.getWebsocket().send(
                JSON.stringify({ type: 'devtools', action: 'get_game_state' })
            );
        },
        commitChanges() {
            const variables = this.buildVariables();
            // preserve which nodes are open
            this.openPaths = this.collectOpenPaths();
            this.busy = true;
            this.getWebsocket().send(
                JSON.stringify({
                    type: 'devtools',
                    action: 'update_game_state',
                    variables: variables,
                })
            );
        },
        handleMessage(message) {
            if (message.type !== 'devtools') return;
            if (message.action === 'game_state') {
                this.loaded = true;
                this.busy = false;
                this.loadVariables(message.data.variables || {});
            } else if (message.action === 'game_state_updated') {
                this.busy = false;
                this.loadVariables(message.data.variables || {});
            }
        },
        // Tree building
        loadVariables(variables) {
            nextId = 1;
            const root = {
                id: newId(),
                label: 'variables',
                kind: 'object',
                children: this.objectChildren(variables),
            };
            this.root = root;
            this.treeItems = root.children;
            // restore open state if available; otherwise open root by default
            if (this.openPaths && this.openPaths.length > 0) {
                this.open = this.restoreOpened(root, this.openPaths);
            } else {
                this.open = [];
            }
        },
        objectChildren(obj) {
            const children = [];
            for (const key of Object.keys(obj || {})) {
                const value = obj[key];
                children.push(this.nodeFromValue(key, value));
            }
            return children;
        },
        arrayChildren(arr) {
            const children = [];
            for (let i = 0; i < (arr || []).length; i++) {
                children.push(this.nodeFromValue(String(i), arr[i], 'array'));
            }
            return children;
        },
        nodeFromValue(key, value, parentKind = 'object') {
            const base = {
                id: newId(),
                key: key,
                parentKind: parentKind,
            };
            if (Array.isArray(value)) {
                return {
                    ...base,
                    label: key,
                    kind: 'array',
                    children: this.arrayChildren(value),
                };
            } else if (value !== null && typeof value === 'object') {
                return {
                    ...base,
                    label: key,
                    kind: 'object',
                    children: this.objectChildren(value),
                };
            } else {
                return {
                    ...base,
                    label: key,
                    kind: 'value',
                    valueType: this.detectType(value),
                    value: value,
                };
            }
        },
        detectType(value) {
            const t = typeof value;
            if (t === 'boolean') return 'bool';
            if (t === 'number') {
                return Number.isInteger(value) ? 'int' : 'float';
            }
            return 'str';
        },
        inputType(valueType) {
            if (valueType === 'int' || valueType === 'float') return 'number';
            return 'text';
        },
        defaultValueForType(valueType) {
            if (valueType === 'bool') return false;
            if (valueType === 'int') return 0;
            if (valueType === 'float') return 0.0;
            return '';
        },
        itemInputValue(item) {
            if (item.valueType === 'bool') return !!item.value;
            return item.value === null || item.value === undefined ? '' : String(item.value);
        },
        setItemInputValue(item, v) {
            if (item.valueType === 'int') {
                const n = parseInt(v, 10);
                item.value = isNaN(n) ? 0 : n;
            } else if (item.valueType === 'float') {
                const f = parseFloat(v);
                item.value = isNaN(f) ? 0 : f;
            } else if (item.valueType === 'bool') {
                item.value = v === true || v === 'true';
            } else {
                item.value = v == null ? '' : String(v);
            }
        },
        toggleBoolValue(item) {
            try {
                item.value = !item.value;
            } catch(e) {}
        },
        // Mutations
        addObjectValue(item, valueType) {
            if (!item.children) item.children = [];
            item.children.push({
                id: newId(),
                key: 'new_key',
                label: 'new_key',
                kind: 'value',
                parentKind: 'object',
                valueType: valueType,
                value: this.defaultValueForType(valueType),
            });
            this.$nextTick(() => {
                if (!this.open.includes(item.id)) {
                    this.open.push(item.id);
                }
                const newlyAdded = item.children[item.children.length - 1];
                // Begin editing newly added item (key first for object children)
                this.$nextTick(() => {
                    this.startEdit(newlyAdded.id, 'key');
                });
            });
        },
        addObjectObject(item) {
            if (!item.children) item.children = [];
            item.children.push({
                id: newId(),
                key: 'new_key',
                label: 'new_key',
                kind: 'object',
                parentKind: 'object',
                children: [],
            });
            this.$nextTick(() => {
                if (!this.open.includes(item.id)) {
                    this.open.push(item.id);
                }
            });
        },
        addObjectArray(item) {
            if (!item.children) item.children = [];
            item.children.push({
                id: newId(),
                key: 'new_key',
                label: 'new_key',
                kind: 'array',
                parentKind: 'object',
                children: [],
            });
            this.$nextTick(() => {
                if (!this.open.includes(item.id)) {
                    this.open.push(item.id);
                }
            });
        },
        addArrayValue(item, valueType) {
            if (!item.children) item.children = [];
            item.children.push({
                id: newId(),
                key: String(item.children.length),
                label: String(item.children.length),
                kind: 'value',
                parentKind: 'array',
                valueType: valueType,
                value: this.defaultValueForType(valueType),
            });
            this.$nextTick(() => {
                if (!this.open.includes(item.id)) {
                    this.open.push(item.id);
                }
                const newlyAdded = item.children[item.children.length - 1];
                // Begin editing newly added item (value first for array children)
                this.$nextTick(() => {
                    this.startEdit(newlyAdded.id, 'value');
                });
            });
        },
        addArrayObject(item) {
            if (!item.children) item.children = [];
            item.children.push({
                id: newId(),
                key: String(item.children.length),
                label: String(item.children.length),
                kind: 'object',
                parentKind: 'array',
                children: [],
            });
            this.$nextTick(() => {
                if (!this.open.includes(item.id)) {
                    this.open.push(item.id);
                }
            });
        },
        addArrayArray(item) {
            if (!item.children) item.children = [];
            item.children.push({
                id: newId(),
                key: String(item.children.length),
                label: String(item.children.length),
                kind: 'array',
                parentKind: 'array',
                children: [],
            });
            this.$nextTick(() => {
                this.open.push(item.id);
            });
        },
        removeNode(item) {
            const root = this.root;
            if (!root || item.id === root.id) return;
            this.removeNodeRecursive(root, item.id);
        },
        removeNodeRecursive(parent, targetId) {
            if (!parent.children) return false;
            const idx = parent.children.findIndex((c) => c.id === targetId);
            if (idx !== -1) {
                parent.children.splice(idx, 1);
                // reindex array keys if needed
                if (parent.kind === 'array') {
                    parent.children.forEach((c, i) => {
                        c.key = String(i);
                        c.label = String(i);
                    });
                }
                return true;
            }
            for (const child of parent.children) {
                if (this.removeNodeRecursive(child, targetId)) return true;
            }
            return false;
        },
        // Serialize
        buildVariables() {
            const root = this.root;
            return this.buildObject(root);
        },
        buildObject(node) {
            const obj = {};
            for (const child of node.children || []) {
                if (child.kind === 'object') {
                    obj[child.key] = this.buildObject(child);
                } else if (child.kind === 'array') {
                    obj[child.key] = this.buildArray(child);
                } else {
                    obj[child.key] = this.castValue(child.valueType, child.value);
                }
            }
            return obj;
        },
        buildArray(node) {
            const arr = [];
            for (const child of node.children || []) {
                if (child.kind === 'object') {
                    arr.push(this.buildObject(child));
                } else if (child.kind === 'array') {
                    arr.push(this.buildArray(child));
                } else {
                    arr.push(this.castValue(child.valueType, child.value));
                }
            }
            return arr;
        },
        castValue(valueType, value) {
            if (valueType === 'bool') return !!value;
            if (valueType === 'int') return parseInt(value, 10) || 0;
            if (valueType === 'float') return parseFloat(value) || 0.0;
            return value == null ? '' : String(value);
        },
        displayValue(node) {
            try {
                if (node.valueType === 'bool') {
                    return node.value ? 'true' : 'false';
                }
                if (node.valueType === 'int' || node.valueType === 'float') {
                    return String(node.value);
                }
                if (node.valueType === 'str') {
                    return String(node.value || '');
                }
                // Fallback
                return String(node.value ?? '');
            } catch(e) {
                return '';
            }
        },
        // Removed Enter-to-add behavior
        onKeyEnter(node) {
            // When pressing Enter in a key field on a value node, move to value edit
            if (!node || node.kind !== 'value') {
                this.stopEdit();
                return;
            }
            // End key editing first, then start value editing next tick to avoid blur race
            this.stopEdit();
            this.$nextTick(() => {
                setTimeout(() => {
                    this.startEdit(node.id, 'value');
                }, 0);
            });
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        if (this.isVisible) {
            this.refresh();
        }
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
};

</script>

<style scoped>
/* Make tree rows more compact */
.gs-tree :deep(.v-list-item) {
    min-height: 28px;
    padding-top: 2px;
    padding-bottom: 2px;
    overflow: visible;
}
.gs-tree :deep(.v-list-item-title),
.gs-tree :deep(.v-list-item-subtitle) {
    line-height: 1.1rem;
    white-space: normal;
}
.gs-tree :deep(.v-list-item-title) {
    overflow: visible;
    display: flex;
    align-items: center;
}
.gs-tree :deep(.v-list-item__content) {
    overflow: visible;
}
.gs-tree :deep(.v-list-item__append) {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 260px;
}
.gs-tree :deep(.v-input__control) {
    min-height: 28px !important;
}
.gs-tree :deep(.v-field) {
    --v-input-control-height: 28px;
}
.gs-tree :deep(.gs-title) {
    width: 100%;
    overflow: visible;
    display: flex;
    align-items: center;
}
/* Inline style replacements */
.gs-maxw-160 { max-width: 160px; }
.gs-maxw-140 { max-width: 140px; }
.gs-minw-0 { min-width: 0; }
.gs-w-100 { width: 100%; }
.gs-value-ellipsis {
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    display: inline-block;
}
</style>


