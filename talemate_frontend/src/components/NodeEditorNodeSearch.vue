<template>
    <v-dialog v-model="dialog" :contained="true" :max-width="800">
        <v-card>
            <v-card-title>Search for Node</v-card-title>
            <v-card-text>
                <v-text-field v-model="searchQuery" label="Search" outlined ref="searchInput" @keydown.down.prevent="focusListItem()" @keydown.enter.prevent="selectSingleItem()"></v-text-field>
                <v-list
                    selectable
                    v-model:selected="selected"
                    select-strategy="single-leaf"
                    style="height: 400px; overflow-y: auto;" 
                    color="primary"
                    ref="nodeList"
                    tabindex="-1">
                    <v-list-item 
                        v-for="node in filteredNodes" 
                        :key="node.registry"
                        :value="node.registry"
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
          let filtered = Object.values(this.nodes).filter(node => {
            const query = this.searchQuery.toLowerCase();
            const title = node.title.toLowerCase();
            const registry = node.registry.toLowerCase();
            
            // Simple includes check for exact matches
            if (title.includes(query) || registry.includes(query)) {
              return true;
            }
            
            // Word-based fuzzy matching: check if all words in query exist in title
            const queryWords = query.split(/\s+/).filter(word => word.length > 0);
            if (queryWords.length > 1) {
              return queryWords.every(word => title.includes(word));
            }
            
            return false;
          });

          // Ensure uniqueness by registry (safeguard against duplicates)
          const uniqueNodes = new Map();
          filtered.forEach(node => {
            if (!uniqueNodes.has(node.registry)) {
              uniqueNodes.set(node.registry, node);
            }
          });
          filtered = Array.from(uniqueNodes.values());

          // sort by match quality: exact matches get highest priority
          filtered.sort((a, b) => {
            const query = this.searchQuery.toLowerCase();
            const aTitle = a.title.toLowerCase();
            const bTitle = b.title.toLowerCase();
            
            // Check what type of match each item is
            const aExactMatch = aTitle.includes(query);
            const bExactMatch = bTitle.includes(query);
            const aStartsWith = aTitle.startsWith(query);
            const bStartsWith = bTitle.startsWith(query);
            
            // Priority 1: Starts with query (highest exact match)
            if (aStartsWith && !bStartsWith) return -1;
            if (!aStartsWith && bStartsWith) return 1;
            
            // Priority 2: Exact substring match
            if (aExactMatch && !bExactMatch) return -1;
            if (!aExactMatch && bExactMatch) return 1;
            
            // Priority 3: Word-based matches (everything else that passed the filter)
            // At this point, both are either exact matches or word matches
            return a.title.localeCompare(b.title);
          });

          return filtered;
        }
    },
    watch: {
        dialog(newVal) {
            if (newVal === true) {
                this.focusSearchInput();
            }
        },
        selected(newVal, oldVal) {
            if (newVal.length > 0 && newVal[0] !== oldVal[0]) {
                this.selectNode(newVal[0]);
            }
        }
    },
    data() {
        return {
            dialog: false,
            searchQuery: '',
            event: null,
            selected: [],
            isProcessingSelection: false
        }
    },
    methods: {
        selectSingleItem() {
            if (this.filteredNodes.length > 0) {
                this.selected = [this.filteredNodes[0].registry];
            }
        },
        focusListItem() {
            if (this.filteredNodes.length > 0) {
                this.$nextTick(() => {
                    if (this.$refs.nodeList) {
                        this.$refs.nodeList.focus();
                    }
                });
            }
        },
        addNode(name) {
            // Use the canvas method to properly add the node
            if (this.canvas) {
                this.graph.beforeChange();
                var node = LiteGraph.createNode(name);

                console.log("ADDING NODE", node);
                
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
        selectNode(nodeRegistry) {
            if (this.isProcessingSelection) return;
            
            this.isProcessingSelection = true;
            this.dialog = false;
            this.addNode(nodeRegistry);
            
            // Reset the flag after a brief delay
            setTimeout(() => {
                this.isProcessingSelection = false;
            }, 300);
        },
        focusSearchInput() {
            // Use both nextTick and setTimeout to ensure DOM is fully updated
            this.$nextTick(() => {
                setTimeout(() => {
                    if (this.$refs.searchInput) {
                        this.$refs.searchInput.focus();
                    }
                }, 50);
            });
        },
        open(event) {
            this.dialog = true;
            this.event = event;
            this.searchQuery = '';
            this.selected = [];
            this.isProcessingSelection = false;
            this.focusSearchInput();
        }
    }
}
</script>
