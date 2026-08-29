/**
 * Turn base64 asset data into an object URL. Callers own the returned URL and
 * must revoke it. Asset data is fine as a data URL on an <img>, but not in
 * CSS: chromium silently drops custom property values over 2 MiB, which scene
 * images exceed as base64.
 */
export function base64ToObjectUrl(base64, mediaType = 'image/png') {
    const binary = window.atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return URL.createObjectURL(new Blob([bytes], { type: mediaType }));
}
