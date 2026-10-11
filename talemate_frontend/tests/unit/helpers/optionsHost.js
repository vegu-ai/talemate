// A host instance without a renderer: data, methods and computed bound to one
// object, with the websocket and autocomplete provider a host injects. A
// completion is delivered through `vm.pendingCompletion`.
export function optionsHost(component, refs = {}) {
    const sent = [];
    const vm = {
        $refs: refs,
        $nextTick: (fn) => fn(),
        $emit() {},
        getWebsocket: () => ({ send: (value) => sent.push(JSON.parse(value)) }),
        autocompleteRequest: (params, done) => { vm.pendingCompletion = done; },
    };
    const parts = [...(component.mixins || []), component];
    for (const part of parts) Object.assign(vm, part.data ? part.data.call(vm) : {});
    vm.source = 'wsm.test';
    for (const part of parts) {
        for (const [key, method] of Object.entries(part.methods || {})) vm[key] = method.bind(vm);
        for (const [key, getter] of Object.entries(part.computed || {})) {
            Object.defineProperty(vm, key, { get: () => getter.call(vm), configurable: true });
        }
    }
    component.created?.call(vm);
    return { vm, sent };
}
