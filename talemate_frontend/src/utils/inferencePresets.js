// Shared reads and mutations for inference presets.
//
// A client either uses the Default group — `presets.inference`, shared by every
// client without a group — or a named group in `presets.inference_groups`.
// The mutations are applied to a config clone through `saveAppConfig`, so they
// must leave the payload complete: the backend validates the whole Config model
// and deletes by omission.

import { hasOwnName, isReservedName } from '@/utils/nameKeyedMap';

// the group key a client carries while it uses the Default presets
export const DEFAULT_GROUP_KEY = '';

export function deepCopy(obj) {
    return JSON.parse(JSON.stringify(obj));
}

export function presetsScope(presets, groupKey) {
    if (!presets) {
        return null;
    }
    if (!groupKey) {
        return presets.inference || null;
    }
    return presets.inference_groups?.[groupKey]?.presets || null;
}

export function presetKeys(presets, groupKey) {
    return Object.keys(presetsScope(presets, groupKey) || {});
}

export function presetLabel(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

export function presetGroupItems(presets) {
    const items = [{ title: 'Default', value: DEFAULT_GROUP_KEY }];
    const groups = presets?.inference_groups;
    if (!groups) {
        return items;
    }
    const named = Object.entries(groups).map(([key, group]) => ({
        title: group.name || key,
        value: key,
    }));
    named.sort((a, b) => a.title.localeCompare(b.title));
    return items.concat(named);
}

// Why a group cannot be created under `name`, or null when it can.
export function groupNameError(presets, name) {
    const trimmed = (name || '').trim();
    if (!trimmed) {
        return 'Enter a name';
    }
    if (isReservedName(trimmed)) {
        return 'That name is reserved';
    }
    if (hasOwnName(presets?.inference_groups, trimmed)) {
        return 'That group already exists';
    }
    return null;
}

export function addPresetGroup(presets, { groupName, sourceGroupKey }) {
    if (groupNameError(presets, groupName)) {
        return null;
    }
    const source = presetsScope(presets, sourceGroupKey);
    if (!source) {
        return null;
    }
    const key = groupName.trim();
    presets.inference_groups[key] = {
        name: key,
        presets: deepCopy(source),
    };
    return key;
}

export function createPresetGroupForClient(config, { clientName, groupName }) {
    // a client name can be any string, `toString` included — an inherited
    // member would pass a plain truthiness check
    if (!hasOwnName(config?.clients, clientName)) {
        return null;
    }
    const client = config.clients[clientName];
    const key = addPresetGroup(config.presets, {
        groupName,
        sourceGroupKey: client.preset_group,
    });
    if (key) {
        client.preset_group = key;
    }
    return key;
}

/**
 * Merges `values` into one preset of a group. Only the fields the caller
 * changed are written, so a save that lands on top of somebody else's edit of
 * the same preset keeps their fields. `changed` is what makes the backend
 * persist a preset, so a write always sets it. Returns false when the group or
 * the preset is gone.
 */
export function writePresetParams(presets, { groupKey, presetKey, values }) {
    const scope = presetsScope(presets, groupKey);
    if (!scope || !scope[presetKey]) {
        return false;
    }
    scope[presetKey] = { ...scope[presetKey], ...deepCopy(values), changed: true };
    return true;
}

/**
 * The fields of `draft` that differ from `baseline`. The panel writes only
 * these, so a save that stacks onto somebody else's edit of the same preset
 * keeps their fields.
 */
export function changedValues(draft, baseline) {
    const changed = {};
    for (const key of Object.keys(draft || {})) {
        if (JSON.stringify(draft[key]) !== JSON.stringify(baseline?.[key])) {
            changed[key] = draft[key];
        }
    }
    return changed;
}

export function panelSettings(presets) {
    return presets?.inference_param_panel || { enabled: false, client: null };
}

// Carries the pinned client through a rename (`newName`) or a removal
// (`newName` null). A pin naming anything else is left alone.
export function movePinnedPanelClient(presets, oldName, newName) {
    const panel = presets?.inference_param_panel;
    if (!panel || panel.client !== oldName) {
        return false;
    }
    panel.client = newName;
    return true;
}
