/**
 * Helpers for the config maps that are keyed by a name the user chose —
 * `config.clients`, `config.agents`, `config.env`.
 *
 * Such a name can be any string, including an Object.prototype member name.
 * On a plain object `map['__proto__'] = entry` hits the prototype setter and
 * creates no key at all, and `'toString' in map` is true with no such entry —
 * so these maps get a null prototype and are probed for own properties only.
 * A row missing from a saved payload is deleted: the backend applies the map
 * it receives by omission.
 */

/**
 * Names a reactive config map cannot carry, so an entry keyed by one of them
 * is unusable in a settings page. They fail in three different ways:
 *
 * - `hasOwnProperty` — the get trap returns Vue's instrumented function, and
 *   `JSON.stringify` omits functions, so the entry never reaches the save
 *   payload at all and the backend deletes it by omission.
 * - `__v_isReactive`, `__v_isShallow` — the lookup resolves to a boolean.
 * - the rest — the edit is written but not tracked, so the dirty check never
 *   sees it and Save stays disabled. `__v_skip`, `__v_raw` and `__v_isReadonly`
 *   make `reactive()` hand back the whole map unproxied, which takes every
 *   other entry on the page down with it.
 *
 * Nothing else is banned: every other `Object.prototype` member name —
 * `constructor`, `toString`, `valueOf`, `isPrototypeOf` — behaves normally and
 * needs only the null-prototype handling below. `nameKeyedMap.spec.js` derives
 * this list from Vue rather than trusting it.
 */
export const REACTIVITY_RESERVED_NAMES = [
    'hasOwnProperty',
    '__proto__',
    '__isVue',
    '__v_isRef',
    '__v_isReactive',
    '__v_isReadonly',
    '__v_isShallow',
    '__v_raw',
    '__v_skip',
];

export function buildNameKeyedPayload(items, entry) {
    const payload = Object.create(null);
    for (const item of items) {
        payload[item.name] = entry(item);
    }
    return payload;
}

export function hasOwnName(map, name) {
    return Object.prototype.hasOwnProperty.call(map || {}, name);
}

/**
 * Copies a name-keyed map onto a null prototype. Entries keep their own key —
 * a key that differs from the entry's own `name` must survive, or the save
 * deletes it by omission.
 */
export function cloneNameKeyedMap(map) {
    const clone = Object.create(null);
    for (const [name, entry] of Object.entries(map || {})) {
        clone[name] = entry;
    }
    return clone;
}

export function isReservedName(name) {
    return REACTIVITY_RESERVED_NAMES.includes(name);
}
