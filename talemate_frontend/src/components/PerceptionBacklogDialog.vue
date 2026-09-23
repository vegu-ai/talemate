<template>
    <v-dialog v-model="dialog" width="560" :persistent="true">
        <v-card v-if="request">
            <v-card-title>
                <v-icon icon="mdi-eye-outline" class="text-primary mr-2" size="small"></v-icon>
                Character perspectives need analysis
            </v-card-title>
            <v-card-text>
                <p class="mb-2">{{ summary }}</p>
                <ul class="mb-3 ml-4">
                    <li v-for="line in details" :key="line">{{ line }}</li>
                </ul>
                <p v-if="queue.length" class="text-muted text-body-small mb-0">
                    <v-icon icon="mdi-layers" size="x-small" class="mr-1"></v-icon>
                    {{ queue.length }} more request{{ queue.length > 1 ? 's' : '' }} waiting
                </p>
            </v-card-text>
            <v-card-actions>
                <v-tooltip location="top" text="Stop now. Talemate asks again the next time it needs these perspectives.">
                    <template v-slot:activator="{ props }">
                        <v-btn v-bind="props" :disabled="responding" @click="respond('cancel')" prepend-icon="mdi-cancel" variant="text">Cancel</v-btn>
                    </template>
                </v-tooltip>
                <v-spacer></v-spacer>
                <v-tooltip location="top" :text="keepTooltip">
                    <template v-slot:activator="{ props }">
                        <v-btn v-bind="props" :disabled="responding" @click="respond('keep')" prepend-icon="mdi-check-all" color="secondary" variant="text">Keep stored perspectives</v-btn>
                    </template>
                </v-tooltip>
                <v-tooltip location="top" :text="analyzeTooltip">
                    <template v-slot:activator="{ props }">
                        <v-btn v-bind="props" :disabled="responding" @click="respond('analyze')" prepend-icon="mdi-eye-refresh-outline" color="primary">{{ analyzeLabel }}</v-btn>
                    </template>
                </v-tooltip>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
function passages(count, kind = '') {
    return `${count} ${kind ? `${kind} ` : ''}passage${count === 1 ? '' : 's'}`;
}

function requests(count) {
    return `${count} request${count === 1 ? '' : 's'}`;
}

export default {
    name: 'PerceptionBacklogDialog',
    inject: ['getWebsocket'],
    data() {
        return {
            dialog: false,
            request: null,
            queue: [],
            responding: false,
        };
    },
    computed: {
        summary() {
            return `${passages(this.request.needed)} need a new perception analysis before the story continues.`;
        },
        details() {
            const lines = [];
            if (this.request.new) lines.push(`${passages(this.request.new, 'new')} ${this.request.new === 1 ? 'comes' : 'come'} from this turn.`);
            if (this.request.keepable) lines.push(`${passages(this.request.keepable)} have stored perspectives that no longer count as current.`);
            if (this.request.empty) lines.push(`${passages(this.request.empty)} lack a stored perspective for at least one character in the scene.`);
            if (this.request.at_risk) lines.push(`A new analysis can also make up to ${passages(this.request.at_risk, 'other')} out of date. They are then analyzed too.`);
            return lines;
        },
        repair() {
            return this.request.requests > this.request.total;
        },
        analyzeLabel() {
            return this.request.at_risk ? `Analyze up to ${this.request.total}` : `Analyze ${this.request.total}`;
        },
        analyzeTooltip() {
            return `Run the analyses now: at most ${requests(this.request.requests)}${this.repair ? ', one repair attempt per analysis included' : ''}.`;
        },
        keepTooltip() {
            const rest = this.request.keep_total
                ? ` ${passages(this.request.keep_total)} are still analyzed, to fill in the missing perspectives: at most ${requests(this.request.keep_requests)}.`
                : ' No request is made.';
            return `Mark the stored perspectives as current without a new analysis.${rest}`;
        },
    },
    methods: {
        // Concurrent requests are answered one at a time; an unanswered one
        // holds its generation until the backend closes it.
        open(data) {
            if (this.request) {
                this.queue.push(data);
                return;
            }
            this.display(data);
        },
        display(data) {
            this.request = data;
            this.responding = false;
            this.dialog = true;
        },
        next() {
            if (this.queue.length) {
                this.display(this.queue.shift());
                return;
            }
            this.dialog = false;
            this.request = null;
            this.responding = false;
        },
        send(requestId, decision) {
            this.getWebsocket().send(JSON.stringify({
                type: 'summarizer',
                action: 'perception_backlog_response',
                request_id: requestId,
                decision,
            }));
        },
        respond(decision) {
            this.responding = true;
            this.send(this.request.request_id, decision);
            this.next();
        },
        dismiss(requestId) {
            this.queue = this.queue.filter((item) => item.request_id !== requestId);
            if (this.request?.request_id === requestId) this.next();
        },
        closeAll() {
            for (const item of [this.request, ...this.queue]) {
                if (item) this.send(item.request_id, 'cancel');
            }
            this.queue = [];
            this.next();
        },
    },
};
</script>
