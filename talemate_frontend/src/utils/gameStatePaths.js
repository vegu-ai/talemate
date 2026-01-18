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
