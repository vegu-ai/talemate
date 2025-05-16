// litegraphUtils.js
import { LGraph, LiteGraph, LGraphCanvas, LGraphNode } from 'litegraph.js';
import { CommentNode } from './commentNode.js';
import { trackRecentNodes } from './recentNodes.js';
import { handleFitGroupToNodes, handleDuplicateGroup, handleVerticalSnapGroup, handleCreateGroupFromSelectedNodes } from './groupInteractions.js';

const UNRESOLVED = "<class 'talemate.game.engine.nodes.core.UNRESOLVED'>";

// Define style presets array
const stylePresets = [
    {
        name: "Agent Generation",
        node_color: "#392c34",
        title_color: "#572e44",
        icon: "F1719"  // robot-happy
    },
    {
        name: "Function Definition",
        node_color: "#392f2c",
        title_color: "#573a2e",
        icon: "F0295"  // function
    },
    {
        name: "Read",
        node_color: "#32422d",
        title_color: "#44552f",
        icon: "F0552"  // download
    },
    {
        name: "Write",
        node_color: "#223040",
        title_color: "#2e4657",
        icon: "F01DA"  // upload
    },
    {
        name: "Delete",
        node_color: "#5f2323",
        title_color: "#7f2e2e",
        icon: "F0683"  // delete-circle
    },
    {
        name: "Error Handling",
        node_color: "#5f2323",
        title_color: "#7f2e2e",
        icon: "F0159"  // alert
    }
    // Add more presets here as needed
];

// Function to apply a preset to a node
function applyStylePreset(node, preset) {
    node.properties.node_color = preset.node_color;
    node.properties.title_color = preset.title_color;
    node.properties.icon = preset.icon;
    
    // Update widgets with new values
    if (node.widgets) {
        node.widgets.forEach(widget => {
            if (widget.name === "node_color") widget.value = preset.node_color;
            if (widget.name === "title_color") widget.value = preset.title_color;
            if (widget.name === "icon") widget.value = preset.icon;
        });
    }
    
    // Update actual node appearance
    if (node.type === "util/ModuleStyle") {
        node.color = preset.title_color;
        node.bgcolor = preset.node_color;
        node.titleIcon = preset.icon;
    }
    
    // Force a redraw of the node's canvas
    if (node.graph && node.graph.list_of_graphcanvas && node.graph.list_of_graphcanvas.length > 0) {
        node.graph.list_of_graphcanvas[0].setDirty(true, true);
    }
}

LiteGraph.alt_drag_do_clone_nodes = true;

// Helper to convert socket types
function convertSocketType(type) {
    if (type === 'any') {
        return '*';
    }
    if (Array.isArray(type)) {
        return type.map(convertSocketType);
    }
    return type;
}

// Helper to determine widget type from field type
function getWidgetType(field) {
    if (field.choices) {
        return 'combo';
    }
    
    switch(field.type) {
        case 'bool':
        case '<class \'bool\'>':
            return 'toggle';
        case 'int':
        case '<class \'int\'>':
            return 'number';
        case 'float':
        case '<class \'float\'>':
            return 'number';
        case 'str':
        case 'blob':
        case '<class \'str\'>':
            return 'text';
        case 'dict':
        case 'list':
        default:
            return 'text';
    }
}

// Function to center the graph canvas on all nodes
export function centerGraphOnNodes(graph) {
    // Make sure the graph has at least one canvas
    if (!graph.list_of_graphcanvas || graph.list_of_graphcanvas.length === 0) {
        console.warn("No canvas found for graph");
        return;
    }
    
    const canvas = graph.list_of_graphcanvas[0];
    
    // If there are no nodes, just reset to default position
    if (!graph._nodes || graph._nodes.length === 0) {
        canvas.ds.offset = [0, 0];
        canvas.setDirty(true, true);
        return;
    }
    
    // Calculate the bounding box of all nodes
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    
    for (const node of graph._nodes) {
        const x = node.pos[0];
        const y = node.pos[1];
        const width = node.size[0];
        const height = node.size[1];
        
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x + width);
        maxY = Math.max(maxY, y + height);
    }
    
    // Calculate the center of the bounding box
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    
    // Get the canvas dimensions
    const canvasWidth = canvas.canvas.width;
    const canvasHeight = canvas.canvas.height;
    
    // Set the offset to center the bounding box
    canvas.ds.offset = [
        canvasWidth / 2 - centerX * canvas.ds.scale,
        canvasHeight / 2 - centerY * canvas.ds.scale
    ];
    
    // Mark the canvas as dirty to trigger a redraw
    canvas.setDirty(true, true);
}

export function centerGraphOnNode(graph, nodeId) {
    const canvas = graph.list_of_graphcanvas[0];
    
    // For LiteGraph, we need to check both _nodes_by_id and _nodes
    let node = graph._nodes_by_id[nodeId];
    
    // If not found by ID, try to find by talemateId
    if (!node && graph._nodes) {
        node = graph._nodes.find(n => n.talemateId === nodeId);
    }
    
    if (node) {
        // Get the center of the node by adding half its width and height
        const nodeCenterX = node.pos[0] + (node.size[0] / 2);
        const nodeCenterY = node.pos[1] + (node.size[1] / 2);
        
        // Set the offset to center the node
        canvas.ds.offset = [
            canvas.canvas.width / 2 - nodeCenterX * canvas.ds.scale,
            canvas.canvas.height / 2 - nodeCenterY * canvas.ds.scale
        ];
        
        canvas.setDirty(true, true);
        return true; // Successfully centered
    }
    
    console.warn("Node not found with ID:", nodeId);
    return false; // Node not found
}

LGraphCanvas.prototype.getExtraMenuOptions = function(node, options) {
    options.push({
        content:"Comment",
        callback: (value, event, mouseEvent, contextMenu) => {
            var first_event = contextMenu.getFirstEvent();
            const node = LiteGraph.createNode("core/Comment");
            node.pos = this.convertEventToCanvasOffset(first_event);
            this.graph.add(node);
        }
    });
};

LGraphCanvas.prototype.createJsonWidgetDraw = function(node, widget_width, y, H, widget) {
    const ctx = this.ctx;
    const margin = 15;
    const outline_color = LiteGraph.WIDGET_OUTLINE_COLOR;
    const background_color = LiteGraph.WIDGET_BGCOLOR;
    const text_color = LiteGraph.WIDGET_TEXT_COLOR;
    const secondary_text_color = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR;
    const show_text = this.ds.scale > 0.5;
    
    // Determine if the value is an array or object and create simplified display
    const value = widget.value || {};
    const isArray = Array.isArray(value);
    const displayValue = isArray ? '[...]' : '{...}';
    
    // Calculate height - now it's just a single line
    const jsonHeight = H; // Simplified height for single line
    
    ctx.textAlign = "left";
    ctx.strokeStyle = outline_color;
    ctx.fillStyle = background_color;
    ctx.beginPath();
    
    if (show_text) {
        ctx.roundRect(margin, y, widget_width - margin * 2, jsonHeight, [H * 0.25]);
    } else {
        ctx.rect(margin, y, widget_width - margin * 2, jsonHeight);
    }
    
    ctx.fill();
    if (show_text && !widget.disabled) {
        ctx.stroke();
    }
    
    if (show_text) {
        // Draw label
        ctx.fillStyle = secondary_text_color;
        const label = widget.label || widget.name;
        if (label != null) {
            ctx.fillText(label, margin * 2, y + H * 0.7);
        }
        
        // Draw simplified JSON content
        ctx.fillStyle = text_color;
        ctx.fillText(displayValue, margin * 2 + ctx.measureText(label + ": ").width, y + H * 0.7);
    }
    
    return jsonHeight; // Return the calculated height
}

// Helper to create a node class from node definition
function createNodeClass(nodeDefinition) {
    function NodeClass() {
        // Add inputs
        nodeDefinition.inputs.forEach((input) => {
            this.addInput(input.name, convertSocketType(input.socket_type));
        });
        
        // Add outputs
        nodeDefinition.outputs.forEach((output) => {
            this.addOutput(output.name, convertSocketType(output.socket_type));
        });
        
        // Set up properties and their widgets
        if (nodeDefinition.fields) {
            this.properties = {};
            Object.entries(nodeDefinition.fields).forEach(([key, field]) => {
                // Set default value if available
                this.properties[key] = field.default !== undefined ? field.default : null;

                // if default is UNRESOLVED, set to null
                if (this.properties[key] === UNRESOLVED) {
                    this.properties[key] = null;
                }

                let widget = null;
                let value = this.properties[key];
                let setter = (v) => { 
                    this.properties[key] = v; 
                    // Automatically update node appearance for ModuleStyle node
                    if (this.type === "util/ModuleStyle") {
                        if (key === "title_color") {
                            this.color = v;
                        } else if (key === "node_color") {
                            this.bgcolor = v;
                        } else if (key === "icon") {
                            this.titleIcon = v;
                        }
                        // Force redraw after property update
                        if (this.graph && this.graph.list_of_graphcanvas && this.graph.list_of_graphcanvas.length > 0) {
                            this.graph.list_of_graphcanvas[0].setDirty(true, true);
                        }
                    }
                };
                
                if (field.type === 'dict' || field.type === 'list') {
                    widget = this.addWidget("json", key, value, setter);
                    // Attach custom draw function
                    widget.draw = (ctx, node, widget_width, y, H) => {
                        return node.graph.list_of_graphcanvas[0].createJsonWidgetDraw(node, widget_width, y, H, widget);
                    };

                    widget.mouse = (ev, coords, node) => {
                        if (ev.type == LiteGraph.pointerevents_method + "down") {
                            const canvas = node.graph.list_of_graphcanvas[0];
                            canvas.prompt(
                                "Value", 
                                JSON.stringify(widget.value || {}, null, 2),
                                (v) => {
                                    widget.value = JSON.parse(v);
                                    node.setProperty(widget.name, widget.value);
                                },
                                ev, 
                                true,
                                (v) => { JSON.parse(v); return v; }
                            );
                        }
                    }

                    // Add custom compute size function
                    widget.computeSize = function(width) {
                        const H = LiteGraph.NODE_WIDGET_HEIGHT;
                        return [
                            width, 
                            H
                        ];
                    };

                } else {
                    // Get appropriate widget type
                    const widgetType = getWidgetType(field);

                    // Add widget based on type
                    if (widgetType === 'combo' && field.choices) {
                        widget = this.addWidget(
                            widgetType,
                            key,
                            value,
                            setter,
                            { values: field.choices }
                        );
                    } else {
                        widget = this.addWidget(
                            widgetType,
                            key,
                            value,
                            setter,
                        );
                    }
                }

                widget.readonly = field.readonly || false;
                widget.disabled = widget.readonly;

                // note: litegraph for some reason applies a hardcoded 0.1 delta to the step value
                // so we need to multiply the step value by 10 to get the correct step value
                if(field.type === 'int') {
                    widget.options.precision = 0;
                    widget.options.step = field.step ? field.step * 10 : 10;
                } else if(field.type === 'float') {
                    widget.options.precision = field.precision || 3;
                    widget.options.step = field.step ? field.step * 10 : 10;
                } else if(field.type === 'text' || field.type === 'blob') {
                    widget.options.multiline = true;
                }


            });
        } else {
            this.properties = {};
        }
        this.titleIcon = "F09DE"; // circle

        if(nodeDefinition.style) {
            this.color = nodeDefinition.style.title_color;
            this.bgcolor = nodeDefinition.style.node_color;
            // Store the icon if provided
            if(nodeDefinition.style.icon) {
                this.titleIcon = nodeDefinition.style.icon;
            }
            // Store auto_title template if provided
            if(nodeDefinition.style.auto_title) {
                this.autoTitleTemplate = nodeDefinition.style.auto_title;
            }
        }
    

        // Store original definition
        this._definition = nodeDefinition;
        
        // Special initialization for ModuleStyle node
        if (this.type === "util/ModuleStyle") {
            // Set initial colors from properties if they exist
            if (this.properties.title_color) {
                this.color = this.properties.title_color;
            }
            if (this.properties.node_color) {
                this.bgcolor = this.properties.node_color;
            }
            if (this.properties.icon) {
                this.titleIcon = this.properties.icon;
            }
        }
    }

    // overwrite contextmenu for node
    NodeClass.prototype.getMenuOptions = function() {
        // Special context menu for ModuleStyle node
        if (this.type === "util/ModuleStyle") {
            // Create submenu items for each preset
            const presetOptions = [];
            
            // Add preset options
            stylePresets.forEach(preset => {
                presetOptions.push({
                    content: preset.name,
                    callback: () => {
                        applyStylePreset(this, preset);
                    }
                });
            });
            
            return [
                {
                    content: "Title",
                    callback: LGraphCanvas.onShowPropertyEditor
                },
                { content: "Pin", callback: LGraphCanvas.onMenuNodePin },
                { 
                    content: "Style Presets",
                    submenu: {
                        options: presetOptions
                    }
                }
            ];
        } else {
            // Default menu for other nodes
            return [
                {
                    content: "Title",
                    callback: LGraphCanvas.onShowPropertyEditor
                },
                { content: "Pin", callback: LGraphCanvas.onMenuNodePin },
            ];
        }
    };

    // Set node title
    NodeClass.title = nodeDefinition.title;
    
    // When a connection is made to a socket where a widget is present, disable the widget
    NodeClass.prototype.onConnectionsChange = function(direction, targetSlot, state, linkInfo, socket) {
        if(direction === LiteGraph.INPUT) {
            if(this.widgets) {
                const widget = this.widgets.find(w => w.name === socket.name);
                if(widget) {
                    widget.disabled = linkInfo && (widget.readonly || state);
                }
            }
        }
    };

    // Define property getters/setters
    if (nodeDefinition.fields) {
        Object.entries(nodeDefinition.fields).forEach(([key]) => {
            Object.defineProperty(NodeClass.prototype, key, {
                get: function() { return this.properties[key]; },
                set: function(v) { 
                    this.properties[key] = v; 
                    // Also update node appearance for ModuleStyle
                    if (this.type === "util/ModuleStyle") {
                        if (key === "title_color") {
                            this.color = v;
                        } else if (key === "node_color") {
                            this.bgcolor = v;
                        } else if (key === "icon") {
                            this.titleIcon = v;
                        }
                        // Force redraw
                        if (this.graph && this.graph.list_of_graphcanvas && this.graph.list_of_graphcanvas.length > 0) {
                            this.graph.list_of_graphcanvas[0].setDirty(true, true);
                        }
                    }
                },
                enumerable: true
            });
        });
    }

    // Add custom drawing to display registry type underneath the node
    NodeClass.prototype.onDrawForeground = function(ctx) {
        // Call the parent method if it exists
        if (LGraphNode.prototype.onDrawForeground) {
            LGraphNode.prototype.onDrawForeground.call(this, ctx);
        }
        
        // Draw the registry type underneath the node
        if (this.type && !this.flags.collapsed) {
            ctx.save();
            
            // Calculate text dimensions and position
            const text = this.type;
            ctx.font = "8px Arial";
            const textMetrics = ctx.measureText(text);
            const textWidth = textMetrics.width;
            
            // Background dimensions
            const padding = 4;
            const bgWidth = textWidth + (padding * 2);
            const bgHeight = 14;
            const radius = 3; // Rounded corner radius
            
            // Position calculations
            const bgX = this.size[0] - bgWidth - 7; // 5px from right edge
            const bgY = this.size[1]; // Positioned at the bottom of the node
            
            // Draw rounded rectangle background
            ctx.fillStyle = "rgb(27, 27, 27, 1)";
            ctx.beginPath();
            
            // Top-left corner (sharp)
            ctx.moveTo(bgX, bgY);
            // Top-right corner (sharp)
            ctx.lineTo(bgX + bgWidth, bgY);
            // Bottom-right corner (rounded)
            ctx.arcTo(bgX + bgWidth, bgY + bgHeight, bgX + bgWidth - radius, bgY + bgHeight, radius);
            // Bottom-left corner (rounded)
            ctx.arcTo(bgX, bgY + bgHeight, bgX, bgY + bgHeight - radius, radius);
            // Back to top-left
            ctx.lineTo(bgX, bgY);
            
            ctx.fill();
            
            // Draw text
            ctx.textAlign = "left";
            ctx.fillStyle = "#ddd"; // Light text color for contrast with black background
            ctx.fillText(text, bgX + padding, bgY + 10); // Position text inside background
            
            ctx.restore();
        }
    };
    // Define a single consistent method for drawing the title box with icon support
    NodeClass.prototype.onDrawTitleBox = function(ctx) {
        // Then draw the icon if it exists
        if(this.titleIcon) {
            ctx.font = "normal normal normal 22px 'Material Design Icons'";
            ctx.fillStyle = this.title_text_color || LiteGraph.NODE_TITLE_COLOR;
            try {
                const iconCode = String.fromCodePoint(parseInt('0x' + this.titleIcon, 16));
                ctx.fillText(iconCode, 5, -7);
            } catch(error) {
                console.error("Error drawing icon for node", this.title, error);
            }
        }
    };

    // handle ctrl+mousedown to set automagic title if style.auto_title is set
    // auto_title will be a javascript format string that will be evaluated
    // e.g., "Custom Title ${node.properties.my_property}"
    if(nodeDefinition.style && nodeDefinition.style.auto_title) {
        NodeClass.prototype.onMouseDown = function(e, pos, graphcanvas) {
            // Check if Ctrl key is pressed
            if(e.shiftKey) {
                try {
                    // Evaluate the template using our simple template engine
                    const newTitle = evaluateSimpleTemplate(this.autoTitleTemplate, this);
                    
                    // Update the node title
                    this.title = newTitle;
                    
                    // Prevent further handling of this event
                    e.stopPropagation();
                    e.preventDefault();
                    
                    // Force a canvas redraw
                    if(graphcanvas) {
                        graphcanvas.setDirty(true, true);
                    }
                    
                    return false;
                } catch(error) {
                    console.error("Error generating auto title:", error);
                    console.error("Template:", this.autoTitleTemplate);
                }
            }
        }
    }

    NodeClass.prototype.clone = function() {
        // Create a new node of the same type
        var newNode = LiteGraph.createNode(this.type);
        if (!newNode) {
            return null;
        }
        
        // Clone position and size
        newNode.pos = [this.pos[0] + 10, this.pos[1] + 10]; // Offset slightly
        newNode.size = [this.size[0], this.size[1]];
        
        // Clone title
        newNode.title = this.title;
        
        // Clone properties
        for (var propName in this.properties) {
            var value = this.properties[propName];
            
            // Deep clone values to avoid reference issues
            if (typeof value === 'object' && value !== null) {
                newNode.properties[propName] = JSON.parse(JSON.stringify(value));
            } else {
                newNode.properties[propName] = value;
            }
        }
        
        // Clone widget values
        if (this.widgets && newNode.widgets) {
            for (var i = 0; i < this.widgets.length && i < newNode.widgets.length; i++) {
                var srcWidget = this.widgets[i];
                var dstWidget = newNode.widgets[i];
                
                // Clone the widget value
                if (srcWidget.name && this.properties[srcWidget.name] !== undefined) {
                    dstWidget.value = this.properties[srcWidget.name];
                }
            }
        }
        
        // Clone flags (including collapsed status)
        if (this.flags) {
            if (!newNode.flags) {
                newNode.flags = {};
            }
            // Clone all flags, including collapsed state
            for (var flagName in this.flags) {
                newNode.flags[flagName] = this.flags[flagName];
            }
        }
        
        return newNode;
    };

    return NodeClass;
}

// Add this function to your litegraphUtils.js
function evaluateSimpleTemplate(template, node) {
    // Replace {propertyName} with node.properties[propertyName]
    return template.replace(/{([^{}]+)}/g, (match, propertyName) => {
        // Get the property value
        const value = node.properties[propertyName];
        
        // Return the value or empty string if undefined/null
        return (value !== undefined && value !== null) ? value : '';
    });
}

// Register all node types from the JSON
export function registerNodesFromJSON(nodeDefinitions) {
    // Register each node type
    LiteGraph.clearRegisteredTypes();
    for(const [nodeType, definition] of Object.entries(nodeDefinitions)) {
        const NodeClass = createNodeClass(definition);
        LiteGraph.registerNodeType(nodeType, NodeClass);
    }
    LiteGraph.registerNodeType("core/Comment", CommentNode);
}

export function lockNode(node, setInherited = false) {
    node.onMouseDown = function() {
        return true;
    };

    node.block_delete = true;
    node.removable = false;
    node.clonable = false;
    node.locked = true;
    node.resizable = false;
    if(setInherited) {
        node.inherited = true;
    }
}

// Create graph from JSON definition
export function createGraphFromJSON(graphData) {
    const graph = new LGraph();
    const nodeMap = new Map();
    
    // Create nodes
    graphData.nodes.forEach(nodeData => {
        const node = LiteGraph.createNode(nodeData.registry);

        if(node) {
            node.pos = [nodeData.x, nodeData.y];
            node.size = [nodeData.width, nodeData.height];
            node.parentId = nodeData.parent;
            node.title = nodeData.title;
            node.talemateId = nodeData.id;
            node.flags.collapsed = nodeData.collapsed;
            
            // Apply properties
            if(nodeData.properties) {

                // properties that come in as "null" need to be converted to null
                Object.keys(nodeData.properties).forEach(key => {
                    if (nodeData.properties[key] === "null") {
                        nodeData.properties[key] = "";
                    }
                });

                Object.assign(node.properties, nodeData.properties);
                // Update widgets with property values
                if (node.widgets) {
                    node.widgets.forEach(widget => {
                        if (nodeData.properties[widget.name] !== undefined) {
                            widget.value = nodeData.properties[widget.name];
                        }
                    });
                }

                // Special handling for ModuleStyle nodes - apply colors directly to node appearance
                if (node.type === "util/ModuleStyle") {
                    if (nodeData.properties.title_color) {
                        node.color = nodeData.properties.title_color;
                    }
                    if (nodeData.properties.node_color) {
                        node.bgcolor = nodeData.properties.node_color;
                    }
                    if (nodeData.properties.icon) {
                        node.titleIcon = nodeData.properties.icon;
                        
                        // Ensure the node will redraw with the icon
                        if (node.graph && node.graph.list_of_graphcanvas && node.graph.list_of_graphcanvas.length > 0) {
                            node.graph.list_of_graphcanvas[0].setDirty(true, true);
                        }
                    }
                }
            }
            
            // Handle inherited nodes
            if (nodeData.inherited === true) {
                lockNode(node, true);
            }
            
            graph.add(node);
            nodeMap.set(nodeData.id, node);
        }
    });

    /* DUPE, WHY IS THIS HERE?
    if (graphData.comments && Array.isArray(graphData.comments)) {
        graphData.comments.forEach(comment => {
          const node = LiteGraph.createNode("core/comment");
          if (node) {
            node.pos = [comment.x, comment.y];
            node.size[0] = comment.width || 200;
            node.properties.text = comment.text || "Comment";
            graph.add(node, false); // Don't compute execution order for comments
          }
        });
      }
    */
    
    // Create connections using socket names
    graphData.connections.forEach(conn => {
        const [fromNodeId, fromSocketName] = conn.from.split('.');
        const [toNodeId, toSocketName] = conn.to.split('.');
        
        const fromNode = nodeMap.get(fromNodeId);
        const toNode = nodeMap.get(toNodeId);
        
        if(fromNode && toNode) {
            const fromSocketIndex = fromNode.outputs.findIndex(
                output => output.name === fromSocketName
            );
            
            const toSocketIndex = toNode.inputs.findIndex(
                input => input.name === toSocketName
            );
            
            if(fromSocketIndex !== -1 && toSocketIndex !== -1) {
                fromNode.connect(fromSocketIndex, toNode, toSocketIndex);

                // toSocket node should disable widget with similar key
                // if it exists (E.g. connected input should disable the widget)
                if(toNode.widgets) {
                    const widget = toNode.widgets.find(w => w.name === toSocketName);
                    if(widget) {
                        widget.disabled = true;
                    }
                }
            }

        }
    });

    // loop through nodes once more to block disconnecting and 
    // connecting of inherited nodes
    for(const node of graph._nodes) {
        if(node.inherited) {
            node.onConnectInput = function() {
                return false;
            };
            node.onConnectOutput = function() {
                return false;
            };
            node.disconnectInput = function() {
                return false;
            };
            node.disconnectOutput = function() {
                return false;
            };
        }
    }

    // create groups
    for(const group of graphData.groups) {
        const node = new LiteGraph.LGraphGroup();
        node.pos = [group.x, group.y];
        node.size = [group.width, group.height];
        node.title = group.title;
        node.font_size = group.font_size;
        node.color = group.color;
        node.inherited = group.inherited || false;

        if(node.inherited) {
            node.title = node.title + " (Inherited, Locked)";
            node.move = function() {
                return false;
            };
        }

        graph.add(node);
    }

    // create comments
    for(const comment of graphData.comments) {
        const node = LiteGraph.createNode("core/Comment");
        node.pos = [comment.x, comment.y];
        node.size = [comment.width, 100];
        node.properties.text = comment.text;
        node.inherited = comment.inherited || false;
        if(node.inherited) {
            lockNode(node, true);
        }
        graph.add(node);
    }


    graph.talemateRegistry = graphData.registry;
    graph.talemateProperties = graphData.properties;
    graph.talemateFields = graphData.fields;
    graph.talemateTitle = graphData.title;
    graph.talemateExtends = graphData.extends;
    graph.setFingerprint = function() {
        this.fingerprint = fingerprintGraph(this);
        //console.log("Fingerprint set", this.fingerprint);
    }.bind(graph);
    graph.hasChanges = function() {
        if(!this.fingerprint) {
            this.setFingerprint();
            return false;
        }
        return !compareFingerprints(this.fingerprint, fingerprintGraph(this));
    }.bind(graph);
    
    return graph;
}

// Fingerprint a graph to determine if it has changed
// The fingerprint will consist of a list of node ids, position, size and connection identifiers
export function fingerprintGraph(graph) {
    let nodes = graph._nodes.map(node => {
        return `${node.talemateId}.${node.pos[0]}.${node.pos[1]}.${node.size[0]}.${node.size[1]}`;
    });
    let connections = Object.values(graph.links).map(link => {

        let copy = {...link};
        // remove _pos and _data
        delete copy._pos;
        delete copy._data;

        const json = JSON.stringify(copy);
        return json;
    });

    // sort both arrays
    nodes.sort();
    connections.sort();

    // remove nodes staqrting with "undefined."
    nodes = nodes.filter(node => !node.startsWith("undefined."));
    return {
        nodes,
        connections
    };

}

// Check if two fingerprints are equal
export function compareFingerprints(fingerprint1, fingerprint2) {

    //console.log(fingerprint1, fingerprint2);

    if(fingerprint1.nodes.length !== fingerprint2.nodes.length) {
        //console.log("FINGERPRINT CHECK: Node length mismatch");
        return false;
    }

    if(fingerprint1.connections.length !== fingerprint2.connections.length) {
        //console.log("FINGERPRINT CHECK: Connection length mismatch");
        return false;
    }

    for(let i = 0; i < fingerprint1.nodes.length; i++) {
        if(fingerprint1.nodes[i] !== fingerprint2.nodes[i]) {
            //console.log("FINGERPRINT CHECK: Node mismatch", fingerprint1.nodes[i], fingerprint2.nodes[i]);
            return false;
        }
    }

    for(let i = 0; i < fingerprint1.connections.length; i++) {
        if(fingerprint1.connections[i] !== fingerprint2.connections[i]) {
            //console.log("FINGERPRINT CHECK: Connection mismatch", fingerprint1.connections[i], fingerprint2.connections[i]);
            return false;
        }
    }

    return true;
}


// Initialize a complete graph from JSON data
export function initializeGraphFromJSON(jsonData, centerToNode) {
    registerNodesFromJSON(jsonData.node_definitions.nodes);
    const graph = createGraphFromJSON(jsonData.graph);

    // Track recent nodes
    trackRecentNodes(graph, 10);

    // Center the graph view - use setTimeout to ensure canvas is ready
    if(!centerToNode) {
        setTimeout(() => {
            centerGraphOnNodes(graph);
        }, 100);
    } else {
        setTimeout(() => {
            centerGraphOnNode(graph, centerToNode);
        }, 100);
    }

    return graph;
}

// Override the processKey method to use our custom cloning for copy/paste
LGraphCanvas.prototype.processKey = function(e) {
    if (!this.graph) {
        return;
    }

    var block_default = false;
    var key_code = e.keyCode;

    // Ctrl+C to copy
    if (e.type == "keydown" && (e.ctrlKey || e.metaKey) && key_code == 67) {
        if (this.selected_nodes) {
            // Store the selected nodes for copy
            var selected_list = [];
            var connection_list = [];
            
            // Create a map of selected nodes by ID for quick lookup
            var selected_map = {};
            
            // First pass: collect selected nodes
            for (var id in this.selected_nodes) {
                var selected_node = this.selected_nodes[id];
                selected_list.push(selected_node);
                // Use talemateId if available, otherwise use id
                selected_map[selected_node.id] = selected_node;
                if (selected_node.talemateId) {
                    selected_map[selected_node.talemateId] = selected_node;
                }
            }
            
            // Second pass: collect connections between selected nodes
            for (var i1 = 0; i1 < selected_list.length; i1++) {
                var source_node = selected_list[i1];
                
                // Check outputs of this node
                if (source_node.outputs) {
                    for (var output_idx = 0; output_idx < source_node.outputs.length; output_idx++) {
                        var output = source_node.outputs[output_idx];
                        if (!output.links || output.links.length === 0) continue;
                        
                        // For each link from this output
                        for (var link_idx = 0; link_idx < output.links.length; link_idx++) {
                            var link_id = output.links[link_idx];
                            var link_info = this.graph.links[link_id];
                            if (!link_info) continue;
                            
                            // Get target node
                            var link_target_node = this.graph.getNodeById(link_info.target_id);
                            if (!link_target_node) continue;
                            
                            // Check if target node is selected
                            if (selected_map[link_target_node.id] || 
                                (link_target_node.talemateId && selected_map[link_target_node.talemateId])) {
                                // Store this connection
                                connection_list.push({
                                    origin_id: source_node.id,
                                    origin_talemateId: source_node.talemateId,
                                    origin_slot: output_idx,
                                    target_id: link_target_node.id,
                                    target_talemateId: link_target_node.talemateId,
                                    target_slot: link_info.target_slot
                                });
                            }
                        }
                    }
                }
            }
            
            // Store the copy data
            LiteGraph._clipboard_data = {
                nodes: selected_list,
                connections: connection_list
            };
        }
        block_default = true;
    } 
    // Ctrl+V to paste
    else if (e.type == "keydown" && (e.ctrlKey || e.metaKey) && key_code == 86) {
        if (LiteGraph._clipboard_data && LiteGraph._clipboard_data.nodes && LiteGraph._clipboard_data.nodes.length) {
            this.graph.beforeChange();
            
            var clipboard_data = LiteGraph._clipboard_data;
            var pasted_nodes = [];
            var old_to_new_ids = {}; // Map from original id to new node id
            
            // Compute center of copied nodes
            var center_x = 0;
            var center_y = 0;
            for (var i2 = 0; i2 < clipboard_data.nodes.length; ++i2) {
                var clipboard_node = clipboard_data.nodes[i2];
                center_x += clipboard_node.pos[0];
                center_y += clipboard_node.pos[1];
            }
            center_x /= clipboard_data.nodes.length;
            center_y /= clipboard_data.nodes.length;
            
            // Get destination position (mouse or center of canvas)
            var mouse_pos = this.last_mouse_position || [
                this.canvas.width * 0.5,
                this.canvas.height * 0.5
            ];
            var offset_pos = this.convertCanvasToOffset(mouse_pos);
            
            // Calculate offset
            var offset_x = offset_pos[0] - center_x;
            var offset_y = offset_pos[1] - center_y;
            
            // First pass: create all nodes
            for (var i3 = 0; i3 < clipboard_data.nodes.length; ++i3) {
                var original_node = clipboard_data.nodes[i3];
                // Remove unused variable
                // var node_type = original_node.type;
                
                // Clone the node
                var new_node = original_node.clone();
                
                // Set new position
                new_node.pos[0] = original_node.pos[0] + offset_x;
                new_node.pos[1] = original_node.pos[1] + offset_y;
                
                // Add to graph
                this.graph.add(new_node);
                
                // Store mapping between old and new IDs
                old_to_new_ids[original_node.id] = new_node.id;
                if (original_node.talemateId) {
                    old_to_new_ids[original_node.talemateId] = new_node.talemateId || new_node.id;
                }
                
                pasted_nodes.push(new_node);
            }
            
            // Second pass: create connections
            for (var i4 = 0; i4 < clipboard_data.connections.length; ++i4) {
                var connection = clipboard_data.connections[i4];
                
                // Get new origin and target nodes
                var origin_id = connection.origin_talemateId || connection.origin_id;
                var target_id = connection.target_talemateId || connection.target_id;
                
                var new_origin_id = old_to_new_ids[origin_id];
                var new_target_id = old_to_new_ids[target_id];
                
                if (!new_origin_id || !new_target_id) continue;
                
                var new_origin_node = this.graph.getNodeById(new_origin_id);
                var new_target_node = this.graph.getNodeById(new_target_id);
                
                if (new_origin_node && new_target_node) {
                    new_origin_node.connect(connection.origin_slot, new_target_node, connection.target_slot);
                }
            }
            
            // Select the pasted nodes
            this.selectNodes(pasted_nodes);
            
            this.graph.afterChange();
        }
        block_default = true;
    }
    // DELETE key - delete selected nodes
    else if (e.type == "keydown" && (key_code == 46 || key_code == 8)) {
        if (this.selected_nodes) {
            this.graph.beforeChange();
            
            for (var delete_id in this.selected_nodes) {
                var node_to_delete = this.selected_nodes[delete_id];
                if (node_to_delete.removable !== false) {
                    this.graph.remove(node_to_delete);
                }
            }
            
            this.selected_nodes = {};
            this.setDirty(true, true);
            this.graph.afterChange();
        }
        block_default = true;
    }

    if (block_default) {
        e.preventDefault();
        e.stopPropagation();
        return false;
    }
};
// Store the original processMouseDown function
const original_processMouseDown = LGraphCanvas.prototype.processMouseDown;

// Override the processMouseDown function
LGraphCanvas.prototype.processMouseDown = function(e) {
    // Basic adjustments and checks from the original function
    if (!this.graph) {
        return;
    }
    this.adjustMouseEvent(e);
    LGraphCanvas.active_canvas = this; // Assign to the static property

    var x = e.clientX;
    var y = e.clientY;
    this.ds.viewport = this.viewport;
    var is_inside = !this.viewport || ( this.viewport && x >= this.viewport[0] && x < (this.viewport[0] + this.viewport[2]) && y >= this.viewport[1] && y < (this.viewport[1] + this.viewport[3]) );

    // If the click is outside the viewport, call the original handler
    if (!is_inside) {
        return original_processMouseDown.call(this, e);
    }

    // --- Custom Group Click Logic ---
    const group = this.graph.getGroupOnPos(e.canvasX, e.canvasY);

    if (group && e.which == 1 && !this.read_only) {
        const titleHeight = LiteGraph.NODE_TITLE_HEIGHT;
        const isClickOnTitle = e.canvasY >= group.pos[1] && e.canvasY < group.pos[1] + titleHeight;

        if (isClickOnTitle) {
            let handled = false;
            // --- Ctrl+Click: Fit Group to Nodes ---
            if (e.ctrlKey || e.metaKey) {
                handled = handleFitGroupToNodes(group, this);
            }
            // --- Shift+Click: Duplicate Group ---
            else if (e.shiftKey) {
                handled = handleDuplicateGroup(group, this);
            }
            // --- Alt+Click: Vertical Snap Group ---
            else if (e.altKey) { 
                handled = handleVerticalSnapGroup(group, this);
            }

            if (handled) {
                e.stopPropagation();
                e.preventDefault();
                return true; // Indicate event was handled by our custom logic
            }
            // If neither Ctrl nor Shift was pressed on the title, allow default behavior (e.g., selection/drag)
        }
    }
    // --- End Group Logic ---

    // If no custom group logic handled the click, proceed with the original logic
    return original_processMouseDown.call(this, e);
};

