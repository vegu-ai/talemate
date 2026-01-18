/**
 * Shared utility for computing ordered reference asset options for character visuals.
 * 
 * Orders assets with explicit references first, then other character assets.
 * Prioritizes same-vis-type assets before falling back to any character assets.
 * Returns the initial selection, ordered list, and reason for selection.
 * 
 * @param {string} targetVisType - The target vis_type (e.g., 'CHARACTER_PORTRAIT', 'CHARACTER_CARD')
 * @param {Array} characterAssets - Array of asset objects with {id, meta, ...} structure (all character assets)
 * @param {string|null} preferredId - Preferred asset ID (e.g., current avatar/cover id)
 * @param {Array|null} sameVisTypeAssets - Optional array of assets with the same vis_type (prioritized first)
 * @param {string|null} fallbackId - Optional fallback asset ID (e.g., cover_image for avatar, avatar for cover)
 * @returns {{selectedId: string|null, orderedIds: string[], reason: string}}
 */
export function computeCharacterReferenceOptions(targetVisType, characterAssets, preferredId = null, sameVisTypeAssets = null, fallbackId = null) {
    if (!characterAssets || characterAssets.length === 0) {
        return {
            selectedId: null,
            orderedIds: [],
            reason: null,
        };
    }

    // Priority 1: Check same-vis-type assets first (if provided)
    if (sameVisTypeAssets && sameVisTypeAssets.length > 0) {
        // Priority 1a: Explicit references in same-vis-type assets
        const sameVisTypeExplicit = sameVisTypeAssets.filter(asset => {
            const referenceTypes = asset?.meta?.reference || [];
            return Array.isArray(referenceTypes) && referenceTypes.includes(targetVisType);
        });
        
        if (sameVisTypeExplicit.length > 0) {
            const selectedId = sameVisTypeExplicit[0].id;
            const orderedIds = buildOrderedList(sameVisTypeExplicit, sameVisTypeAssets, characterAssets, selectedId, targetVisType);
            return {
                selectedId,
                orderedIds,
                reason: 'Explicit reference asset marked for ' + targetVisType + ' use',
            };
        }
        
        // Priority 1b: Preferred ID in same-vis-type assets
        if (preferredId) {
            const preferredAsset = sameVisTypeAssets.find(a => a.id === preferredId);
            if (preferredAsset) {
                const orderedIds = buildOrderedList([], sameVisTypeAssets, characterAssets, preferredId, targetVisType);
                return {
                    selectedId: preferredId,
                    orderedIds,
                    reason: 'Default avatar for this character',
                };
            }
        }
        
        // Priority 1c: First available same-vis-type asset
        const firstSameVisType = sameVisTypeAssets[0];
        const orderedIds = buildOrderedList([], sameVisTypeAssets, characterAssets, firstSameVisType.id, targetVisType);
        return {
            selectedId: firstSameVisType.id,
            orderedIds,
            reason: 'First available ' + targetVisType + ' avatar',
        };
    }

    // Priority 2: Check all character assets for explicit references
    const explicitReferences = characterAssets.filter(asset => {
        const referenceTypes = asset?.meta?.reference || [];
        return Array.isArray(referenceTypes) && referenceTypes.includes(targetVisType);
    });
    
    if (explicitReferences.length > 0) {
        const selectedId = explicitReferences[0].id;
        const orderedIds = buildOrderedList(explicitReferences, [], characterAssets, selectedId, targetVisType);
        return {
            selectedId,
            orderedIds,
            reason: 'Character asset explicitly marked as reference for ' + targetVisType,
        };
    }
    
    // Priority 3: Preferred ID in all character assets
    if (preferredId) {
        const preferredAsset = characterAssets.find(a => a.id === preferredId);
        if (preferredAsset) {
            const orderedIds = buildOrderedList([], [], characterAssets, preferredId, targetVisType);
            return {
                selectedId: preferredId,
                orderedIds,
                reason: 'Preferred asset for this character',
            };
        }
    }
    
    // Priority 4: Fallback ID (e.g., cover_image for avatar, avatar for cover)
    if (fallbackId) {
        const fallbackAsset = characterAssets.find(a => a.id === fallbackId);
        if (fallbackAsset) {
            const meta = fallbackAsset?.meta || {};
            if (meta.character_name) {
                const orderedIds = buildOrderedList([], [], characterAssets, fallbackId, targetVisType);
                const fallbackType = targetVisType === 'CHARACTER_PORTRAIT' ? 'cover image' : 'avatar';
                return {
                    selectedId: fallbackId,
                    orderedIds,
                    reason: fallbackType.charAt(0).toUpperCase() + fallbackType.slice(1) + ' explicitly set on this character',
                };
            }
        }
    }
    
    // Priority 5: First available character asset
    const firstAsset = characterAssets[0];
    const orderedIds = buildOrderedList([], [], characterAssets, firstAsset.id, targetVisType);
    return {
        selectedId: firstAsset.id,
        orderedIds,
        reason: 'First available character asset (any type)',
    };
}

/**
 * Build ordered list: selected first, then explicit references, then same-vis-type (if provided), then others
 */
function buildOrderedList(explicitReferences, sameVisTypeAssets, allCharacterAssets, selectedId, targetVisType) {
    const orderedIds = [];
    const includedIds = new Set();
    
    // Add selected first
    if (selectedId) {
        orderedIds.push(selectedId);
        includedIds.add(selectedId);
    }
    
    // Add explicit references (excluding selected)
    for (const asset of explicitReferences) {
        if (!includedIds.has(asset.id)) {
            orderedIds.push(asset.id);
            includedIds.add(asset.id);
        }
    }
    
    // Add same-vis-type assets (excluding already included)
    if (sameVisTypeAssets && sameVisTypeAssets.length > 0) {
        for (const asset of sameVisTypeAssets) {
            if (!includedIds.has(asset.id)) {
                orderedIds.push(asset.id);
                includedIds.add(asset.id);
            }
        }
    }
    
    // Add other character assets (excluding already included)
    for (const asset of allCharacterAssets) {
        if (!includedIds.has(asset.id)) {
            orderedIds.push(asset.id);
            includedIds.add(asset.id);
        }
    }
    
    return orderedIds;
}
