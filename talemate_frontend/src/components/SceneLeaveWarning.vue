<template></template>

<script>
export default {
    props: {
        active: Boolean,
        saved: { type: Boolean, default: true },
    },
    computed: {
        shouldWarn() {
            return this.active && this.saved === false;
        },
    },
    watch: {
        shouldWarn: {
            immediate: true,
            handler(enabled) {
                if (enabled) window.addEventListener('beforeunload', this.beforeUnload);
                else window.removeEventListener('beforeunload', this.beforeUnload);
            },
        },
    },
    methods: {
        beforeUnload(event) {
            if (!this.shouldWarn) return;
            event.preventDefault();
            event.returnValue = '';
        },
    },
    beforeUnmount() {
        window.removeEventListener('beforeunload', this.beforeUnload);
    },
};
</script>
