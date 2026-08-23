/**
 * Extract paths from a game state variables object.
 * 
 * @param {Object} obj - The game state variables object
 * @param {string} prefix - Current path prefix (used for recursion)
 * @param {Object} options - Options object
 * @param {boolean} options.includeContainers - If true, include container paths (dicts/objects) in addition to leaf paths
 * @returns {string[]} Array of paths
 */
export function extractGameStatePaths(obj, prefix = '', options = {}) {
    const { includeContainers = false } = options;
    const paths = [];
    
    if (obj === null || obj === undefined) {
        return paths;
    }
    
    if (typeof obj !== 'object' || Array.isArray(obj)) {
        // Leaf value (primitive or array), return the path
        if (prefix) {
            paths.push(prefix);
        }
        return paths;
    }
    
    // It's an object/dict
    for (const [key, value] of Object.entries(obj)) {
        const currentPath = prefix ? `${prefix}/${key}` : key;
        
        if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
            // Nested object/dict
            if (includeContainers) {
                // Include the container path itself
                paths.push(currentPath);
            }
            // Recursively extract paths from nested objects
            paths.push(...extractGameStatePaths(value, currentPath, options));
        } else {
            // Leaf value (primitive or array)
            paths.push(currentPath);
        }
    }
    
    return paths;
}

export function getGameStateValue(variables, path) {
    if (!path) return undefined;

    let value = variables;
    for (const part of path.split('/')) {
        if (value === null || value === undefined || typeof value !== 'object') {
            return undefined;
        }
        value = value[part];
    }

    return value;
}

export function setGameStateValue(variables, path, newValue) {
    const updated = JSON.parse(JSON.stringify(variables || {}));
    const parts = path.split('/');
    let current = updated;

    for (const part of parts.slice(0, -1)) {
        if (current[part] === undefined || current[part] === null) {
            current[part] = {};
        }
        current = current[part];
    }

    current[parts[parts.length - 1]] = newValue;
    return updated;
}

export function expandGameStatePaths(paths, variables) {
    const expanded = [];
    const seen = new Set();

    for (const path of paths || []) {
        if (!path) continue;

        const value = getGameStateValue(variables, path);
        if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
            const keys = Object.keys(value).filter(Boolean).sort();
            if (keys.length) {
                for (const key of keys) {
                    const childPath = `${path}/${key}`;
                    if (!seen.has(childPath)) {
                        seen.add(childPath);
                        expanded.push(childPath);
                    }
                }
                continue;
            }
        }

        if (!seen.has(path)) {
            seen.add(path);
            expanded.push(path);
        }
    }

    return expanded;
}

export function resolveGameStatePathSettings(scene, displayPath) {
    const configured = scene?.data?.game_state_path_settings || {};
    const own = configured[displayPath] || {};

    // the settings map is shared by both pin targets and the backend resolves
    // read-only over the whole of it, so inheritance is keyed on the map
    // itself rather than on the pin list of the target being drawn
    const ancestors = Object.keys(configured)
        .filter((path) => displayPath.startsWith(`${path}/`))
        .sort((left, right) => right.length - left.length);

    let label = own.label || '';
    if (!label) {
        const labeled = ancestors.find((path) => configured[path].label);
        if (labeled) {
            const childPath = displayPath.slice(labeled.length + 1)
                .split('/')
                .join(' / ');
            label = `${configured[labeled].label} / ${childPath}`;
        }
    }

    // a container's description describes the group, so it passes down as
    // written rather than composed the way the label is
    let description = own.description || '';
    if (!description) {
        const described = ancestors.find((path) => configured[path].description);
        description = described ? configured[described].description : '';
    }

    let order = own.order ?? null;
    if (order === null) {
        const ordered = ancestors.find((path) => (configured[path].order ?? null) !== null);
        order = ordered ? configured[ordered].order : null;
    }

    return {
        label,
        description,
        minimum: own.minimum ?? null,
        maximum: own.maximum ?? null,
        step: own.step ?? null,
        slider: Boolean(own.slider),
        choices: own.choices || [],
        read_only: Boolean(own.read_only)
            || ancestors.some((path) => configured[path].read_only),
        order,
    };
}

export function sortGameStatePathsByOrder(scene, displayPaths) {
    return displayPaths
        .map((path, index) => ({
            path,
            index,
            order: resolveGameStatePathSettings(scene, path).order,
        }))
        .sort((left, right) => (
            (left.order ?? Number.MAX_SAFE_INTEGER) - (right.order ?? Number.MAX_SAFE_INTEGER)
            || left.index - right.index
        ))
        .map((entry) => entry.path);
}
