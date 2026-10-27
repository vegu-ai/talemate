// Targets of the scene_assets set_asset action: where an asset is shown.
export const assetTarget = {
    message: (messageId, { overrideCadence = false } = {}) => ({
        kind: 'message',
        message_id: messageId,
        override_cadence: overrideCadence,
    }),
    backdropEntry: (messageId) => ({ kind: 'backdrop_entry', message_id: messageId }),
    sceneBackdrop: () => ({ kind: 'scene_backdrop' }),
    sceneCover: () => ({ kind: 'scene_cover' }),
    characterCover: (characterName) => ({ kind: 'character_cover', character_name: characterName }),
    characterAvatar: (characterName, slot = 'default') => ({
        kind: 'character_avatar',
        character_name: characterName,
        slot,
    }),
};

export function setAssetMessage(assetId, targets, { replace = false } = {}) {
    const message = { type: 'scene_assets', action: 'set_asset', asset_id: assetId, targets };
    if (replace) message.replace = true;
    return message;
}

export function enableSceneBackdropMessage() {
    return { type: 'scene_assets', action: 'set_scene_backdrop', enabled: true };
}
