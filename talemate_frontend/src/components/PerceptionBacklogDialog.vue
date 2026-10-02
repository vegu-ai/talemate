<template>
    <v-dialog v-model="dialog" width="560" :persistent="true">
        <v-card v-if="request">
            <v-card-title>
                <v-icon icon="mdi-eye-outline" class="text-primary mr-2" size="small"></v-icon>
                {{ title }}
            </v-card-title>
            <v-card-text>
                <template v-if="hasPerceptions">
                    <p class="mb-2">{{ summary }}</p>
                    <ul class="mb-3 ml-4">
                        <li v-for="line in details" :key="line">{{ line }}</li>
                    </ul>
                </template>
                <template v-if="hasSummaries">
                    <p class="mb-2">{{ summariesSummary }}</p>
                    <ul class="mb-3 ml-4">
                        <li v-for="line in summariesDetails" :key="line">{{ line }}</li>
                    </ul>
                </template>
                <p v-if="queue.length" class="text-muted text-body-small mb-0">
                    <v-icon icon="mdi-layers" size="x-small" class="mr-1"></v-icon>
                    {{ queue.length }} more request{{ queue.length > 1 ? 's' : '' }} waiting
                </p>
            </v-card-text>
            <v-card-actions>
                <v-tooltip location="top" :text="cancelTooltip">
                    <template v-slot:activator="{ props }">
                        <v-btn v-bind="props" :disabled="responding" @click="respond('cancel')" prepend-icon="mdi-cancel" variant="text">Cancel</v-btn>
                    </template>
                </v-tooltip>
                <v-spacer></v-spacer>
                <v-tooltip location="top" :text="keepTooltip">
                    <template v-slot:activator="{ props }">
                        <v-btn v-bind="props" :disabled="responding" @click="respond('keep')" prepend-icon="mdi-check-all" color="secondary" variant="text">{{ keepLabel }}</v-btn>
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

function characterSummaries(count, kind = '') {
    return `${count} ${kind ? `${kind} ` : ''}character summar${count === 1 ? 'y' : 'ies'}`;
}

function list(items) {
    return items.length > 1 ? `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}` : `${items[0]}`;
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
        perceptions() {
            return this.request.perceptions;
        },
        summaries() {
            return this.request.summaries;
        },
        hasPerceptions() {
            return Boolean(this.perceptions);
        },
        hasSummaries() {
            return Boolean(this.summaries);
        },
        both() {
            return this.hasPerceptions && this.hasSummaries;
        },
        title() {
            if (this.both) return 'Character knowledge needs an update';
            return this.hasSummaries ? 'Character summaries need a rebuild' : 'Character perspectives need analysis';
        },
        summary() {
            return `${passages(this.perceptions.needed)} need a new perception analysis before the story continues.`;
        },
        details() {
            const p = this.perceptions;
            const lines = [];
            if (p.new) lines.push(`${passages(p.new, 'new')} ${p.new === 1 ? 'comes' : 'come'} from this turn.`);
            if (p.keepable) lines.push(`${passages(p.keepable)} have stored perspectives that no longer count as current.`);
            if (p.empty) lines.push(`${passages(p.empty)} lack a stored perspective for at least one character in the scene.`);
            if (p.at_risk) lines.push(`A new analysis can also make up to ${passages(p.at_risk, 'other')} out of date. They are then analyzed too.`);
            return lines;
        },
        summariesSummary() {
            const rebuild = this.summaries.rebuild;
            const layers = rebuild.layers.length > 1 ? `layers ${list(rebuild.layers)}` : `layer ${rebuild.layers[0]}`;
            const after = this.hasPerceptions ? ', or will be after the analysis' : '';
            return `Up to ${characterSummaries(rebuild.total)} for ${list(rebuild.characters)} (${layers}) ${rebuild.total === 1 ? 'is' : 'are'} out of date${after}. What is rebuilt depends on your choice:`;
        },
        summariesDetails() {
            const { rebuild, keep } = this.summaries;
            const cascade = rebuild.at_risk
                ? `, including up to ${characterSummaries(rebuild.at_risk, 'layered')} that a rebuild makes out of date`
                : '';
            const kept = keep.keepable ? ` and keeps ${keep.keepable} as stored` : '';
            return [
                `"${this.rebuildChoice}" rebuilds up to ${rebuild.total}${cascade}.`,
                `"${this.keepLabel}" rebuilds ${keep.keep_total || 'none'}${kept}.`,
            ];
        },
        repair() {
            return this.perceptions.requests > this.perceptions.total;
        },
        rebuildChoice() {
            return this.both ? 'Analyze and rebuild' : 'Rebuild';
        },
        analyzeLabel() {
            if (this.both) return 'Analyze and rebuild';
            if (this.hasSummaries) {
                const rebuild = this.summaries.rebuild;
                return rebuild.at_risk ? `Rebuild up to ${rebuild.total}` : `Rebuild ${rebuild.total}`;
            }
            const p = this.perceptions;
            return p.at_risk ? `Analyze up to ${p.total}` : `Analyze ${p.total}`;
        },
        keepLabel() {
            if (this.both) return 'Keep stored';
            return this.hasSummaries ? 'Keep current summaries' : 'Keep stored perspectives';
        },
        analyzeTooltip() {
            const parts = [];
            if (this.hasPerceptions) parts.push(`Run the analyses now: at most ${requests(this.perceptions.requests)}${this.repair ? ', one repair attempt per analysis included' : ''}.`);
            if (this.hasSummaries) parts.push(`Rebuild the summaries${this.both ? ' after them' : ' now'}, one at a time: at most ${requests(this.summaries.rebuild.requests)}.`);
            return parts.join(' ');
        },
        keepTooltip() {
            const parts = [];
            if (this.hasPerceptions) {
                const p = this.perceptions;
                const rest = p.keep_total
                    ? ` ${passages(p.keep_total)} are still analyzed, to fill in the missing perspectives: at most ${requests(p.keep_requests)}.`
                    : ' No request is made.';
                parts.push(`Mark the stored perspectives as current without a new analysis.${rest}`);
            }
            if (this.hasSummaries) {
                const keep = this.summaries.keep;
                const rest = keep.keep_total
                    ? ` ${characterSummaries(keep.keep_total)} ${keep.keep_total === 1 ? 'is' : 'are'} still rebuilt: at most ${requests(keep.keep_requests)}.`
                    : ' No summary request is made.';
                parts.push(`Mark the stored character summaries as current as they are.${rest}`);
            }
            return parts.join(' ');
        },
        cancelTooltip() {
            const subject = this.both ? 'them' : this.hasSummaries ? 'these summaries' : 'these perspectives';
            return `Stop now. Talemate asks again the next time it needs ${subject}.`;
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
