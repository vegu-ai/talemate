export const EDITABLE_MODULE_PROPERTY_TYPES = [
    "str",
    "color",
    "int",
    "float",
    "bool",
    "text",
    "icon",
];

export function hasEditableProperties(fields) {
    for (const key in fields || {}) {
        if (EDITABLE_MODULE_PROPERTY_TYPES.includes((fields[key] || {}).type)) {
            return true;
        }
    }
    return false;
}
