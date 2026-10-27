/**
 * Registers a component as an image paste target for as long as it is mounted.
 *
 * The component provides `handlePastedImage(file)`. A component that declares
 * a `pasteTargetEnabled` computed takes a paste only while it is truthy. The
 * registered element is the component's root.
 */

import { registerImagePasteTarget } from '@/utils/imagePaste';

export default {
    mounted() {
        this._unregisterImagePasteTarget = registerImagePasteTarget({
            getElement: () => this.$el,
            handler: (file) => this.handlePastedImage(file),
            isEnabled: () => !('pasteTargetEnabled' in this) || !!this.pasteTargetEnabled,
        });
    },
    beforeUnmount() {
        if (this._unregisterImagePasteTarget) {
            this._unregisterImagePasteTarget();
            this._unregisterImagePasteTarget = null;
        }
    },
}
