<template>
    <v-card v-if="plan" class="plan-banner mb-2" variant="outlined" density="compact">
        <v-card-text class="pa-2">
            <div class="d-flex align-center justify-space-between">
                <div class="d-flex align-center">
                    <v-icon size="small" class="mr-1">mdi-clipboard-list-outline</v-icon>
                    <span class="text-body-small font-weight-medium">Plan</span>
                    <v-chip
                        size="x-small"
                        label
                        :color="planStatusColor"
                        class="ml-2"
                    >{{ plan.status }}</v-chip>
                    <span class="text-body-small text-muted ml-2">{{ completedCount }}/{{ plan.tasks.length }}</span>
                </div>
                <v-btn
                    size="x-small"
                    icon
                    variant="text"
                    density="compact"
                    @click="collapsed = !collapsed"
                >
                    <v-icon>{{ collapsed ? 'mdi-chevron-down' : 'mdi-chevron-up' }}</v-icon>
                </v-btn>
            </div>
            <v-expand-transition>
                <div v-show="!collapsed" class="mt-2">
                    <!-- Completed summary -->
                    <div v-if="hiddenBeforeCount > 0" class="d-flex align-center text-body-small text-muted completed-summary" @click="showAll = !showAll">
                        <v-icon size="x-small" class="mr-1" color="success">mdi-check-circle</v-icon>
                        <span>{{ hiddenBeforeCount }} completed task{{ hiddenBeforeCount > 1 ? 's' : '' }}</span>
                        <v-icon size="x-small" class="ml-1">{{ showAll ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
                    </div>
                    <!-- Task list -->
                    <div
                        v-for="task in displayedTasks"
                        :key="task.id"
                        class="d-flex align-center task-row"
                    >
                        <v-icon
                            size="x-small"
                            :color="taskIconColor(task)"
                            class="mr-1"
                        >{{ taskIcon(task) }}</v-icon>
                        <span class="text-body-small task-description" :class="{ 'text-muted': task.status === 'completed' || task.status === 'skipped' }">{{ task.description }}</span>
                        <v-spacer />
                        <v-chip
                            size="x-small"
                            label
                            :color="taskStatusColor(task)"
                            class="ml-1"
                        >{{ task.status }}</v-chip>
                    </div>
                    <!-- Hidden after summary -->
                    <div v-if="hiddenAfterCount > 0" class="d-flex align-center text-body-small text-muted completed-summary" @click="showAll = !showAll">
                        <v-icon size="x-small" class="mr-1">mdi-circle-outline</v-icon>
                        <span>{{ hiddenAfterCount }} more pending task{{ hiddenAfterCount > 1 ? 's' : '' }}</span>
                        <v-icon size="x-small" class="ml-1">mdi-chevron-down</v-icon>
                    </div>
                    <!-- Show less -->
                    <div v-if="showAll && isWindowable" class="d-flex align-center text-body-small text-muted completed-summary" @click="showAll = false">
                        <v-icon size="x-small" class="mr-1">mdi-unfold-less-horizontal</v-icon>
                        <span>Show less</span>
                    </div>
                </div>
            </v-expand-transition>
        </v-card-text>
    </v-card>
</template>

<script>
const CONTEXT_BEFORE = 1;
const CONTEXT_AFTER = 2;

export default {
    name: 'DirectorConsoleChatPlanBanner',
    props: {
        plan: {
            type: Object,
            default: null,
        },
    },
    data() {
        return {
            collapsed: false,
            showAll: false,
        };
    },
    computed: {
        completedCount() {
            if (!this.plan || !this.plan.tasks) return 0;
            return this.plan.tasks.filter(t => t.status === 'completed').length;
        },
        planStatusColor() {
            const colors = {
                planning: 'info',
                ready: 'primary',
                executing: 'warning',
                completed: 'success',
                cancelled: 'error',
            };
            return colors[this.plan.status] || 'default';
        },
        activeIndex() {
            if (!this.plan || !this.plan.tasks) return -1;
            const idx = this.plan.tasks.findIndex(t => t.status === 'executing');
            if (idx !== -1) return idx;
            return this.plan.tasks.findIndex(t => t.status === 'pending');
        },
        windowRange() {
            if (!this.plan || !this.plan.tasks) return { start: 0, end: 0 };
            const total = this.plan.tasks.length;
            if (this.showAll || total <= CONTEXT_BEFORE + CONTEXT_AFTER + 1) {
                return { start: 0, end: total };
            }
            const anchor = this.activeIndex >= 0 ? this.activeIndex : total;
            const start = Math.max(0, anchor - CONTEXT_BEFORE);
            const end = Math.min(total, anchor + CONTEXT_AFTER + 1);
            return { start, end };
        },
        displayedTasks() {
            if (!this.plan || !this.plan.tasks) return [];
            const { start, end } = this.windowRange;
            return this.plan.tasks.slice(start, end);
        },
        hiddenBeforeCount() {
            return this.windowRange.start;
        },
        hiddenAfterCount() {
            if (!this.plan || !this.plan.tasks) return 0;
            return this.plan.tasks.length - this.windowRange.end;
        },
        isWindowable() {
            if (!this.plan || !this.plan.tasks) return false;
            return this.plan.tasks.length > CONTEXT_BEFORE + CONTEXT_AFTER + 1;
        },
    },
    methods: {
        taskStatusColor(task) {
            const colors = {
                pending: 'default',
                executing: 'warning',
                completed: 'success',
                skipped: 'muted',
            };
            return colors[task.status] || 'default';
        },
        taskIcon(task) {
            const icons = {
                pending: 'mdi-circle-outline',
                executing: 'mdi-progress-clock',
                completed: 'mdi-check-circle',
                skipped: 'mdi-skip-next-circle',
            };
            return icons[task.status] || 'mdi-circle-outline';
        },
        taskIconColor(task) {
            return this.taskStatusColor(task);
        },
    },
}
</script>

<style scoped>
.plan-banner {
    border-color: rgba(var(--v-theme-primary), 0.3);
}
.task-row {
    padding: 2px 0;
    min-height: 24px;
}
.task-description {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.completed-summary {
    cursor: pointer;
    padding: 2px 0;
    opacity: 0.7;
}
.completed-summary:hover {
    opacity: 1;
}
</style>
