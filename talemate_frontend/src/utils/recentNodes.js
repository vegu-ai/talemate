/**
 * Add the recent nodes feature to a graph
 * @param {LGraph} graph - The graph to add the feature to
 * @param {number} max_recent_nodes - Maximum number of recent nodes to track
 * @return {LGraph} The modified graph
 */
import { LiteGraph, LGraphCanvas } from 'litegraph.js';
import { handleCreateGroupFromSelectedNodes } from './groupInteractions.js';

// Track if we've already modified the canvas prototype
let canvasPrototypeModified = false;

export function trackRecentNodes(graph, max_recent_nodes = 10) {
    // Add recent_nodes array to the graph if it doesn't exist
    if (!graph.recent_nodes) {
        graph.recent_nodes = [];
    }
    
    graph.max_recent_nodes = max_recent_nodes;
    
    // Store the original onNodeAdded function
    const original_onNodeAdded = graph.onNodeAdded;
    
    // Override the onNodeAdded function to track recent nodes
    graph.onNodeAdded = function(node) {
        // Call the original onNodeAdded function if it exists
        if (original_onNodeAdded) {
            original_onNodeAdded.call(this, node);
        }
        
        // Add the node type to the recent_nodes array
        const nodeType = node.type;
        
        // Skip if node.type is undefined
        if (!nodeType) {
            return;
        }
        
        // Check if the node type is already in the array
        const index = this.recent_nodes.indexOf(nodeType);
        
        // If the node type is already in the array, remove it
        if (index !== -1) {
            this.recent_nodes.splice(index, 1);
        }
        
        // Add the node type to the beginning of the array
        this.recent_nodes.unshift(nodeType);
        
        // Limit the array to the specified limit
        if (this.recent_nodes.length > this.max_recent_nodes) {
            this.recent_nodes.pop();
        }
    };
    
    // Only modify the canvas prototype once
    if (!canvasPrototypeModified) {
        // Modify the getCanvasMenuOptions function to include recent nodes
        const original_getCanvasMenuOptions = LGraphCanvas.prototype.getCanvasMenuOptions;
        
        LGraphCanvas.prototype.getCanvasMenuOptions = function() {
            const options = original_getCanvasMenuOptions.call(this);
            
            // Add "Create Group from Selection" option if there are selected nodes
            if (this.selected_nodes && Object.keys(this.selected_nodes).length > 0) {
                // Check if the option already exists to avoid duplicates
                const hasCreateGroupOption = options.some(
                    item => item && item.content === "Create Group from Selection"
                );
                
                if (!hasCreateGroupOption) {
                    // Add a separator if there isn't one at the beginning
                    if (options.length > 0 && options[0] !== null) {
                        options.unshift(null);
                    }
                    
                    // Add the option to create a group from selected nodes with presets submenu
                    options.unshift({
                        content: "Create Group from Selection",
                        has_submenu: true,
                        callback: (value, opts, e, prev_menu) => {
                            // Build submenu with color previews (same style as Edit Group -> Color)
                            const colors = LGraphCanvas.node_colors || {};
                            const makeColorItem = (label, key) => {
                                const c = colors[key];
                                const html = c
                                    ? `<span style='display: block; color: #999; padding-left: 4px; border-left: 8px solid ${c.color}; background-color:${c.bgcolor}'>${label}</span>`
                                    : label;
                                return {
                                    content: html,
                                    callback: (v, o, ev, menu) => {
                                        handleCreateGroupFromSelectedNodes(this, { colorKey: key, title: label });
                                        if (menu && typeof menu.getTopMenu === 'function') {
                                            menu.getTopMenu().close();
                                        }
                                    }
                                };
                            };

                            const entries = [
                                { content: "Default", callback: (v, o, ev, menu) => { handleCreateGroupFromSelectedNodes(this); if (menu && menu.getTopMenu) menu.getTopMenu().close(); } },
                                null,
                                makeColorItem("Output", 'green'),
                                makeColorItem("Process", 'pale_blue'),
                                makeColorItem("Prepare", 'cyan'),
                                makeColorItem("Validation", 'yellow'),
                                makeColorItem("Function", 'brown'),
                                makeColorItem("Special", 'purple'),
                                makeColorItem("Error Handling", 'red'),
                                makeColorItem("Input", 'blue'),
                                makeColorItem("UX", 'teal'),
                            ];

                            new LiteGraph.ContextMenu(entries, {
                                event: e,
                                parentMenu: prev_menu,
                                allow_html: true
                            });
                        }
                    });
                }
            }
            
            // Add recent nodes to the menu if there are any
            if (this.graph && this.graph.recent_nodes && this.graph.recent_nodes.length > 0) {
                // Check if "Recently Added Nodes" title already exists in the menu
                const hasTitleAlready = options.some(
                    item => item && item.content === "Recently Added Nodes"
                );
                
                if (!hasTitleAlready) {
                    // Add a separator (null entry creates a horizontal line)
                    options.push(null);
                    
                    // Add a label for the recent nodes section
                    options.push({
                        content: "Recently Added Nodes",
                        is_title: true, // This is just a visual indicator, not clickable
                        disabled: true
                    });
                    
                    // Add each recent node directly to the menu
                    for (const nodeType of this.graph.recent_nodes) {
                        // Get the node constructor
                        const nodeConstructor = LiteGraph.registered_node_types[nodeType];
                        
                        // Use the constructor title if available, otherwise use the node type
                        const title = nodeConstructor ? (nodeConstructor.title || nodeType) : nodeType;
                        
                        options.push({
                            content: title,
                            callback: function() {
                                // Create a new node of the selected type
                                const canvas = LGraphCanvas.active_canvas;
                                if (!canvas) return;
                                
                                canvas.graph.beforeChange();
                                const newNode = LiteGraph.createNode(nodeType);
                                if (newNode) {
                                    // Position at mouse or center of canvas if no mouse event
                                    const pos = canvas.last_mouse_position || [
                                        canvas.canvas.width * 0.5, 
                                        canvas.canvas.height * 0.5
                                    ];
                                    newNode.pos = canvas.convertCanvasToOffset(pos);
                                    canvas.graph.add(newNode);
                                }
                                canvas.graph.afterChange();
                            }
                        });
                    }
                }
            }
            
            return options;
        };
        
        // Mark that we've modified the prototype
        canvasPrototypeModified = true;
    }
    
    return graph;
}