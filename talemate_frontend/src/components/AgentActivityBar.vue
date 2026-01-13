<template>
  <v-sheet color="transparent" class="mb-1" style="min-height: 32px;">
    <div class="d-flex flex-wrap align-center" style="gap: 4px;">
      <transition-group name="fade" tag="div" class="d-flex flex-wrap align-center" style="gap: 4px;">
        <v-chip
          v-for="agent in activeAgents"
          :key="agent.name"
          size="x-small"
          variant="tonal"
          :color="agent.busy_bg ? 'secondary' : 'primary'"
          class="ma-1"
        >
          {{ agent.label }}
          <span v-if="getActionDescription(agent)" class="ml-1 text-muted">
            · {{ getActionDescription(agent) }}
          </span>
        </v-chip>
      </transition-group>
    </div>
  </v-sheet>
</template>

<script>
export default {
  name: 'AgentActivityBar',
  props: {
    agentStatus: {
      type: Object,
      required: true,
      default: () => ({})
    }
  },
  data() {
    return {
      arrivalOrder: {} // Track when each agent became busy
    };
  },
  computed: {
    activeAgents() {
      return Object.values(this.agentStatus)
        .filter(agent => agent.busy && agent.name !== 'memory') // Exclude memory agent
        .sort((a, b) => {
          // Sort by arrival time (oldest first, newest last/rightmost)
          const timeA = this.arrivalOrder[a.name] || 0;
          const timeB = this.arrivalOrder[b.name] || 0;
          return timeA - timeB;
        });
    },
    hasActiveAgents() {
      return this.activeAgents.length > 0;
    }
  },
  watch: {
    agentStatus: {
      deep: true,
      handler(newStatus) {
        Object.values(newStatus).forEach(agent => {
          if (agent.busy && !this.arrivalOrder[agent.name]) {
            // Agent just became busy, record arrival time
            this.arrivalOrder[agent.name] = Date.now();
          } else if (!agent.busy && this.arrivalOrder[agent.name]) {
            // Agent is no longer busy, remove from tracking
            delete this.arrivalOrder[agent.name];
          }
        });
      }
    }
  },
  methods: {
    getActionDescription(agent) {
      // Get current action from meta
      if (agent.meta && agent.meta.current_action) {
        // Convert snake_case to Title Case for better readability
        return agent.meta.current_action
          .replace(/_/g, ' ')
          .replace(/\b\w/g, char => char.toUpperCase());
      }
      return "Processing";
    }
  }
};
</script>

<style scoped>
.text-muted {
  opacity: 0.7;
}

/* Fade transition */
.fade-leave-active {
  transition: opacity 0.5s ease;
}

.fade-leave-to {
  opacity: 0;
}

.fade-move {
  transition: transform 0.5s ease;
}
</style>
