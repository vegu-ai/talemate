<template>

    <v-card  class="ma-0 sticky-right" :width="expanded ? 400 : 76" ref="container" elevation="7">
        <v-list max-height="720" style="overflow-y: auto;" density="compact">
            <v-row no-gutters>
                <v-col :cols="expanded ? 6 : 12">
                    <v-btn color="secondary" variant="text" size="small" @click="expanded = !expanded" :prepend-icon="expanded ? 'mdi-menu-up' : 'mdi-menu-down'" text>Log</v-btn>
                </v-col>
                <v-col :cols="expanded ? 6 : 0" v-if="expanded" class="text-right">
                    <v-btn color="delete" variant="text" size="small" @click="clearLog" :prepend-icon="'mdi-close-circle-outline'">Clear</v-btn>
                </v-col>
            </v-row>   
            
            <div v-if="expanded === true">
                <v-list-item v-for="entry in log" :key="entry.entryId" @click="inspectNode = entry; inspect = true;">
                    <v-list-item-title :class="'text-' + entry.color">
                        {{ entry.title }} <span class="text-caption text-muted">{{ entry.nodeId.slice(0,4) }}</span></v-list-item-title>
                    <v-list-item-subtitle>{{ entry.value }}</v-list-item-subtitle>
                </v-list-item>
            </div>
        </v-list>

    </v-card>

    <v-dialog v-model="inspect" max-width="600" :contained="true">
        <v-card>
            <v-card-title>
                {{ inspectNode.title }}
                <v-chip color="grey-lighten-1" variant="text">{{ inspectNode.nodeId.slice(0,8) }}</v-chip>
                <v-chip size="small" label class="mr-1" color="primary" variant="tonal"><strong class="mr-1">type</strong>{{ inspectNode.nodeType }}</v-chip>
            </v-card-title>
            <v-card-text class="text-caption">
                <div max-height="600" style="overflow-y: auto;" class="value-display text-muted">
                {{ inspectNode.value }}
                </div>
            </v-card-text>
        </v-card>
    </v-dialog>
</template>

<script>

export default {
  name: 'NodeEditorLog',
  props: {
    maxEntries: {
      type: Number,
      default: 200,
    }
  },
  data: function() {
    return {
      log: [],
      expanded: true,
      inspect: false,
      inspectNode: null,
      entryIdCounter: 0,
      lastClearTime: null,
    }
  },
  methods:{
    width: function() {
      return this.$refs.container.$el.offsetWidth;
    },
    addMockEntries(num = 50) {
        for (let i = 0; i < num; i++) {
            this.log.unshift({
                entryId: this.entryIdCounter++,
                title: "Node " + i, 
                nodeId: "node" + i, 
                value: Math.random(), 
                timestamp: new Date(), 
                nodeType: "mock"
            });
        }
    },
    clearLog() {
        // Store the timestamp of the most recent entry before clearing
        if (this.log.length > 0 && this.log[0].endTime) {
            this.lastClearTime = this.log[0].endTime;
        }
        this.log = [];
    },
    addEntry(node, value, state) {

        // does value end with "UNRESOLVED'>"
        if(value.endsWith("UNRESOLVED'>")) {
            return;
        }

        // if last entry in log is identical to new value, do nothing
        if (this.log.length > 0 && this.log[0].value === value && this.log[0].nodeId === node.talemateId) {
            return;
        }
        
        // Skip if entry's end_time is less than the most recent entry's end_time
        if (this.log.length > 0 && this.log[0].endTime && state.end_time < this.log[0].endTime) {
            return;
        }
        
        // Skip if entry's end_time is less than when the log was last cleared
        if (this.lastClearTime && state.end_time && state.end_time < this.lastClearTime) {
            return;
        }

        this.log.unshift({
            entryId: this.entryIdCounter++,
            title: node.title,
            nodeId: node.talemateId, 
            value: value, 
            startTime: state.start_time,
            endTime: state.end_time,
            runTime: (state.end_time ? state.end_time - state.start_time : null),
            nodeType: node.type,
            color: state.error ? 'error' : null,
        });

        while (this.log.length > this.maxEntries) {
            this.log.pop();
        }
    }
  },
  //mounted() {
  // this.addMockEntries();
  //}
}
</script>

<style scoped>

.sticky-right {
    position: absolute;
    right: 0px;
    top: 50px;
    width: 400px;
    z-index: 10;
}

.value-display {
    white-space: pre-wrap;
}

</style>