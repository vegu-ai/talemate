<template>
    <v-dialog v-model="dialog" :contained="true" :max-width="800">
        <v-card>
            <v-card-title>Search for Node</v-card-title>
            <v-card-text>
                <v-text-field v-model="searchQuery" label="Search" outlined ref="searchInput" @keydown.enter.prevent="handleEnterKey" @keydown.down.prevent="focusList"></v-text-field>
                <v-list 
                    style="height: 400px; overflow-y: auto;" 
                    color="primary"
                    ref="nodeList"
                    tabindex="-1"
                    @keydown.down.prevent="navigateList(1)" 
                    @keydown.up.prevent="navigateList(-1)"
                    @keydown.enter.prevent="selectFocusedNode">
                    <v-list-item 
                        v-for="(node, index) in filteredNodes" 
                        :key="node.id" 
                        @click="selectNode(node)"
                        :class="{ 'v-list-item--active': focusedIndex === index }"
                        tabindex="0"
                        ref="listItems">
                        <v-list-item-title>{{ node.title }}</v-list-item-title>
                        <v-list-item-subtitle>{{ node.registry }}</v-list-item-subtitle>
                    </v-list-item>
                </v-list>
            </v-card-text>

        </v-card>
    </v-dialog>
</template>

<script>
import { LiteGraph } from 'litegraph.js';

export default {
    name: 'NodeEditorNodeSearch',
    props: {
        nodes: Object,
        graph: Object,
        canvas: Object,
    },
    computed: {
        filteredNodes() {
          if(!this.searchQuery || !this.nodes || this.nodes.length === 0) {
            return [];
          }

          // filter by node.registry and node.title
          // nodes is an object literal with keys as the node type and values as the node definition
          // so we need to filter by the node definition title and registry
          return Object.values(this.nodes).filter(node => {
            return node.title.toLowerCase().includes(this.searchQuery.toLowerCase()) || node.registry.toLowerCase().includes(this.searchQuery.toLowerCase());
          });
        }
    },
    watch: {
        nodes(newVal) {
            console.log("nodes", newVal);
        }
    },
    data() {
        return {
            dialog: false,
            searchQuery: '',
            event: null,
            focusedIndex: -1,
            isProcessingSelection: false
        }
    },
    methods: {
        focusList() {
            if (this.filteredNodes.length > 0) {
                this.focusedIndex = 0;
                this.$nextTick(() => {
                    if (this.$refs.nodeList) {
                        this.$refs.nodeList.focus();
                    }
                });
            }
        },
        navigateList(direction) {
            if (this.filteredNodes.length === 0) return;
            
            const newIndex = this.focusedIndex + direction;
            if (newIndex >= 0 && newIndex < this.filteredNodes.length) {
                this.focusedIndex = newIndex;
            }
        },
        selectFocusedNode() {
            if (this.focusedIndex >= 0 && this.focusedIndex < this.filteredNodes.length && !this.isProcessingSelection) {
                this.selectNode(this.filteredNodes[this.focusedIndex]);
            }
        },
        handleEnterKey() {
            // Only proceed if there are filtered nodes and we're not already processing a selection
            if (this.filteredNodes.length > 0 && this.focusedIndex === -1 && !this.isProcessingSelection) {
                this.selectNode(this.filteredNodes[0]);
            }
        },
        addNode(name) {
            // Use the canvas method to properly add the node
            if (this.canvas) {
                this.graph.beforeChange();
                var node = LiteGraph.createNode(name);
                
                if (node) {
                    // Position the node at the event location
                    node.pos = this.canvas.convertEventToCanvasOffset(this.event);
                    
                    // Add the node through canvas (this handles updating the UI)
                    this.graph.add(node);
                    
                    this.graph.afterChange();
                    this.canvas.setDirty(true, true);
                    
                    // Force a redraw
                    this.canvas.draw(true, true);
                }
            }
        },
        selectNode(node) {
            if (this.isProcessingSelection) return;
            
            this.isProcessingSelection = true;
            this.dialog = false;
            this.addNode(node.registry);
            
            // Reset the flag after a brief delay
            setTimeout(() => {
                this.isProcessingSelection = false;
            }, 300);
        },
        open(event) {
            this.dialog = true;
            this.event = event;
            this.searchQuery = '';
            this.focusedIndex = -1;
            this.isProcessingSelection = false;
            this.$nextTick(() => {
                if (this.$refs.searchInput) {
                    this.$refs.searchInput.focus();
                }
            });
        }
    }
}
</script>
