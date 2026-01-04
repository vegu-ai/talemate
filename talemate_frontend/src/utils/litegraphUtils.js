// litegraphUtils.js
import { LGraph, LiteGraph, LGraphCanvas, LGraphNode } from 'litegraph.js';
import { CommentNode } from './commentNode.js';
import { trackRecentNodes } from './recentNodes.js';
import { handleFitGroupToNodes, handleDuplicateGroup, handleVerticalSnapGroup, handleCreateGroupFromSelectedNodes } from './groupInteractions.js';
import { handleWatchNodeShortcut, handleSetStateNodeShortcut, handleStageNodeShortcut } from './graphConnectionUtil.js';

const UNRESOLVED = "<class 'talemate.game.engine.nodes.core.UNRESOLVED'>";

export function normalizeHexColor(value) {
    // Accept Vuetify string formats; persist as #RRGGBB.
    if (value && typeof value === 'object') {
        if (typeof value.hex === 'string') value = value.hex;
        else if (typeof value.hexa === 'string') value = value.hexa;
    }

    if (value == null || value === '') {
        return '';
    }

    if (typeof value !== 'string') {
        throw new Error('Invalid color value');
    }

    let v = value.trim();
    if (!v.startsWith('#')) {
        v = `#${v}`;
    }

    // Expand shorthand #RGB -> #RRGGBB
    if (/^#[0-9a-fA-F]{3}$/.test(v)) {
        v = `#${v[1]}${v[1]}${v[2]}${v[2]}${v[3]}${v[3]}`;
    }

    // Drop alpha if present (#RRGGBBAA -> #RRGGBB)
    if (/^#[0-9a-fA-F]{8}$/.test(v)) {
        v = v.slice(0, 7);
    }

    if (!/^#[0-9a-fA-F]{6}$/.test(v)) {
        throw new Error('Color must be in #RRGGBB format');
    }

    return v.toUpperCase();
}

// Initialize node_colors if not already defined (extends LiteGraph's default colors)
if (!LGraphCanvas.node_colors) {
    LGraphCanvas.node_colors = {};
}

// Add or extend color definitions for groups
LGraphCanvas.node_colors.teal = {
    color: "#00796B",      // teal darken-3 (for title/border)
    bgcolor: "#004D40",    // teal darken-4 (for background - very dark)
    groupcolor: "#00796B"  // teal darken-4 (for group color - very dark)
};

// Define style presets array (mutable to allow session-only additions)
let stylePresets = [
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
    },
    {
        name: "Talemate Tint",
        node_color: "#27233a",
        title_color: "#3d315b",
        icon: "F09DE"  // circle
    },
    {
        name: "Async Agent Generation",
        node_color: "#1e3a38",
        title_color: "#2d5a55",
        icon: "F16A3"  // robot-excited
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
    if (field.choices && field.choices.length > 0) {
        return 'combo';
    }
    
    switch(field.type) {
        case 'bool':
        case '<class \'bool\'>':
            return 'toggle';
        case 'number':
        case 'int':
        case '<class \'int\'>':
        case 'float':
        case '<class \'float\'>':
            return 'number';
        case 'color':
            return 'color';
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

function drawColorWidget(ctx, node, widget_width, y, H, widget) {
    const margin = 15;
    const outline_color = LiteGraph.WIDGET_OUTLINE_COLOR;
    const background_color = LiteGraph.WIDGET_BGCOLOR;
    const text_color = LiteGraph.WIDGET_TEXT_COLOR;
    const secondary_text_color = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR;

    const canvas = node && node.graph && node.graph.list_of_graphcanvas && node.graph.list_of_graphcanvas[0]
        ? node.graph.list_of_graphcanvas[0]
        : null;
    const show_text = canvas ? canvas.ds.scale > 0.5 : true;

    const raw = widget.value == null ? "" : String(widget.value);
    const swatch = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(raw) ? raw : "#000000";

    ctx.textAlign = "left";
    ctx.strokeStyle = outline_color;
    ctx.fillStyle = background_color;
    ctx.beginPath();

    if (show_text) {
        ctx.roundRect(margin, y, widget_width - margin * 2, H, [H * 0.5]);
    } else {
        ctx.rect(margin, y, widget_width - margin * 2, H);
    }

    ctx.fill();
    if (show_text && !widget.disabled) {
        ctx.stroke();
    }

    if (show_text) {
        const label = widget.label || widget.name;
        ctx.fillStyle = secondary_text_color;
        if (label != null) {
            ctx.fillText(label, margin * 2, y + H * 0.7);
        }

        // Value text (left of swatch)
        ctx.fillStyle = text_color;
        ctx.textAlign = "right";

        const swatchSize = Math.max(10, Math.floor(H * 0.6));
        const swatchX = widget_width - margin * 2;
        const swatchY = y + Math.floor((H - swatchSize) / 2);

        // Draw swatch border
        ctx.save();
        ctx.fillStyle = swatch;
        ctx.strokeStyle = outline_color;
        ctx.beginPath();
        if (ctx.roundRect) {
            ctx.roundRect(swatchX - swatchSize, swatchY, swatchSize, swatchSize, [2]);
        } else {
            ctx.rect(swatchX - swatchSize, swatchY, swatchSize, swatchSize);
        }
        ctx.fill();
        ctx.stroke();
        ctx.restore();

        // Draw the value text
        const display = raw.length > 30 ? raw.slice(0, 30) : raw;
        ctx.fillText(display, swatchX - swatchSize - 6, y + H * 0.7);
        ctx.textAlign = "left";
    }

    return H;
}

function handleColorWidgetMouse(ev, coords, node, widget, field) {
    if (ev.type !== LiteGraph.pointerevents_method + "down") {
        return false;
    }

    const canvas = node && node.graph && node.graph.list_of_graphcanvas && node.graph.list_of_graphcanvas[0]
        ? node.graph.list_of_graphcanvas[0]
        : null;
    if (!canvas) {
        return false;
    }

    const title = field && field.description ? field.description : (widget.label || widget.name || "Color");
    canvas.prompt(
        "Value",
        widget.value || "",
        (v) => {
            widget.value = v;
            // Prefer the widget callback (our `setter`) so ModuleStyle styling updates.
            if (widget.callback) {
                widget.callback(widget.value, canvas, node, coords, ev);
            } else {
                node.setProperty(widget.name, widget.value);
            }
        },
        ev,
        false,
        null,
        { editorType: "color", title }
    );

    return true;
}

// Helper to create a node class from node definition
function createNodeClass(nodeDefinition) {
    function NodeClass() {
        // Add inputs
        nodeDefinition.inputs.forEach((input) => {
			this.addInput(input.name, convertSocketType(input.socket_type), { optional: input.optional });
        });
        
        // Add outputs
        nodeDefinition.outputs.forEach((output) => {
			this.addOutput(output.name, convertSocketType(output.socket_type), { optional: output.optional });
        });
        
        // Set up properties and their widgets
        if (nodeDefinition.fields) {
            this.properties = {};
            Object.entries(nodeDefinition.fields).forEach(([key, field]) => {
                // Set default value if available
                this.properties[key] = field.default !== undefined ? field.default : null;

                // if property is still not set, check if nodeDefinition.properties has as value
                if(!this.properties[key] && nodeDefinition.properties && nodeDefinition.properties[key]) {
                    this.properties[key] = nodeDefinition.properties[key];
                }

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
                    if (widgetType === 'color') {
                        widget = this.addWidget(
                            "color",
                            key,
                            value,
                            setter,
                        );

                        // Render like a text widget with a color swatch.
                        widget.draw = (ctx, node, widget_width, y, H) => {
                            return drawColorWidget(ctx, node, widget_width, y, H, widget);
                        };

                        widget.mouse = (ev, coords, node) => {
                            return handleColorWidgetMouse(ev, coords, node, widget, field);
                        };

                        widget.computeSize = function(width) {
                            const H = LiteGraph.NODE_WIDGET_HEIGHT;
                            return [width, H];
                        };

                    } else if (widgetType === 'combo' && field.choices) {
                        // Sort choices alphabetically (supports primitives or {label, value})
                        const sortedChoices = Array.isArray(field.choices)
                            ? field.choices.slice().sort((a, b) => {
                                const aText = (a && typeof a === 'object' && 'label' in a) ? String(a.label) : String(a);
                                const bText = (b && typeof b === 'object' && 'label' in b) ? String(b.label) : String(b);
                                return aText.localeCompare(bText, undefined, { sensitivity: 'base' });
                            })
                            : field.choices;
                        widget = this.addWidget(
                            widgetType,
                            key,
                            value,
                            setter,
                            { values: sortedChoices }
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
            // Store counterpart action metadata if provided
            if(nodeDefinition.style.counterpart) {
                this.shiftCopy = nodeDefinition.style.counterpart;
            }
        }
    

        // Store original definition
        this._definition = nodeDefinition;
        
        // Check for dynamic socket support
        if (nodeDefinition.supports_dynamic_sockets) {
            this.supportsDynamicSockets = true;
            this.dynamicInputType = nodeDefinition.dynamic_input_type || 'any';
            this.dynamicInputLabel = nodeDefinition.dynamic_input_label || 'input{i}';
        }
        
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
            
            // Add separator and "Remember for this session" option
            presetOptions.push(null); // separator
            presetOptions.push({
                content: "Remember for this session",
                callback: () => {
                    // Get the canvas to use for prompting
                    const canvas = this.graph && this.graph.list_of_graphcanvas && this.graph.list_of_graphcanvas.length > 0
                        ? this.graph.list_of_graphcanvas[0]
                        : null;
                    
                    if (!canvas) {
                        console.error("Cannot find canvas for prompt");
                        return;
                    }
                    
                    // Prompt for preset name
                    canvas.prompt(
                        "Preset Name",
                        "",
                        (presetName) => {
                            if (!presetName || presetName.trim() === "") {
                                return; // User cancelled or entered empty name
                            }
                            
                            // Extract current style from the node
                            const currentStyle = {
                                name: presetName.trim(),
                                node_color: this.properties.node_color || this.bgcolor || "",
                                title_color: this.properties.title_color || this.color || "",
                                icon: this.properties.icon || this.titleIcon || "F09DE"
                            };
                            
                            // Check if a preset with this name already exists
                            const existingIndex = stylePresets.findIndex(p => p.name === currentStyle.name);
                            if (existingIndex !== -1) {
                                // Update existing preset
                                stylePresets[existingIndex] = currentStyle;
                            } else {
                                // Add new preset
                                stylePresets.push(currentStyle);
                            }
                            
                            // Force canvas redraw to update context menu if it's open
                            canvas.setDirty(true, true);
                        },
                        null, // event
                        false, // multiline
                        null, // validator
                        null  // options
                    );
                }
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
            const options = [
                {
                    content: "Title",
                    callback: LGraphCanvas.onShowPropertyEditor
                },
                { content: "Pin", callback: LGraphCanvas.onMenuNodePin },
            ];
            
            // Add dynamic input options for supported node types
            const hasDynamicSockets = this.supportsDynamicSockets || (this._definition && this._definition.supports_dynamic_sockets);
            if (hasDynamicSockets) {
                // Ensure inputs array exists
                if (!this.inputs) {
                    this.inputs = [];
                }
                options.push(null); // separator
                options.push({
                    content: "Add Input Slot",
                    callback: () => {
                        // Set flag to preserve width during this operation
                        this._preserveWidthOnNextResize = true;
                        const count = (this.inputs || []).filter(i => i.dynamic).length;
                        const socketType = this.dynamicInputType || 'any';
                        const socket = this.addInput(this.dynamicInputLabel.replace('{i}', count), socketType);
                        socket.dynamic = true; // Mark as dynamic
                        this.setDirtyCanvas(true, true);
                    }
                });
                
                // Only show remove option if there are dynamic inputs
                const dynamicInputs = (this.inputs || []).filter(i => i.dynamic);
                if (dynamicInputs.length > 0) {
                    options.push({
                        content: "Remove Last Input",
                        callback: () => {
                            // Set flag to preserve width during this operation
                            this._preserveWidthOnNextResize = true;
                            const lastDynamic = dynamicInputs[dynamicInputs.length - 1];
                            const index = this.inputs.indexOf(lastDynamic);
                            this.removeInput(index);
                            this.setDirtyCanvas(true, true);
                        }
                    });
                }
            }
            
            return options;
        }
    };

    // Set node title
    NodeClass.title = nodeDefinition.title;
    
    // Patch: Custom computeSize to remove bottom gap if no sockets and add space for dynamic buttons
    NodeClass.prototype.computeSize = function() {
        const size = LGraphNode.prototype.computeSize.call(this);
        const gap = 20;
        const noSockets = (
            (!this.inputs || this.inputs.length === 0) &&
            (!this.outputs || this.outputs.length === 0)
        );

        if(noSockets) {
            size[1] = size[1] - gap;
        }

        // Add extra space for dynamic socket buttons if supported
        // Check both the property and the original definition in case property isn't set yet during initialization
        const hasDynamicSockets = this.supportsDynamicSockets || (this._definition && this._definition.supports_dynamic_sockets);
        if (hasDynamicSockets) {
            size[1] += 35; // Extra space for buttons and padding - increased for better separation
        }

        // Only preserve width during dynamic socket operations, not during manual resizing
        // We check if this is being called from a socket addition operation
        if (this.size && this.size[0] > size[0] && this._preserveWidthOnNextResize) {
            size[0] = this.size[0];
            // Reset the flag after using it
            this._preserveWidthOnNextResize = false;
        }

        return size;
    };


    // When a connection is made to a socket where a widget is present, disable the widget
    NodeClass.prototype.onConnectionsChange = function(direction, targetSlot, state, linkInfo, socket) {
        if(direction === LiteGraph.INPUT) {
            if(this.widgets) {
                const widget = this.widgets.find(w => w.name === socket.name);
                if(widget) {
                    const connected = !!state;
                    widget.disabled = (connected || widget.readonly);

                    // Mask widget value while connected so the property value isn't displayed
                    if (connected) {
                        if (!widget._masked_due_to_connection) {
                            widget._masked_due_to_connection = true;
                            widget._value_before_mask = widget.value;
                            widget.value = "";
                        }
                    } else {
                        if (widget._masked_due_to_connection) {
                            // Restore from properties if available, otherwise from backup
                            const restore = (this.properties && this.properties.hasOwnProperty(widget.name))
                                ? this.properties[widget.name]
                                : widget._value_before_mask;
                            widget.value = restore;
                            delete widget._value_before_mask;
                            widget._masked_due_to_connection = false;
                        }
                    }
                    this.setDirtyCanvas(true, true);
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
        
        // Draw + and - buttons for dynamic socket nodes
        // Check both the property and the original definition in case property isn't set yet during initialization
        const hasDynamicSockets = this.supportsDynamicSockets || (this._definition && this._definition.supports_dynamic_sockets);
        if (hasDynamicSockets && !this.flags.collapsed) {
            const buttonSize = 18;
            const buttonPadding = 8;
            const buttonAreaHeight = 30; // Dedicated area height for buttons at bottom
            
            // Position buttons in dedicated area at the very bottom of the node
            // Calculate the actual socket area height to position buttons below it
            const socketAreaHeight = this.size[1] - buttonAreaHeight;
            const buttonY = socketAreaHeight + (buttonAreaHeight - buttonSize) / 2; // Center buttons in the button area
            
            // Calculate button positions - back to original X positions, new Y position
            const addButtonX = buttonPadding; // Original left position
            const addButtonY = buttonY;
            const removeButtonX = this.size[0] - buttonSize - buttonPadding; // Original right position  
            const removeButtonY = buttonY;
            
            ctx.save();
            
            // Draw a subtle separator line above the button area
            ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(5, socketAreaHeight + 2);
            ctx.lineTo(this.size[0] - 5, socketAreaHeight + 2);
            ctx.stroke();
            
            // Draw add button (+) on the left
            ctx.fillStyle = "#4CAF50"; // Green
            ctx.beginPath();
            ctx.roundRect(addButtonX, addButtonY, buttonSize, buttonSize, 3);
            ctx.fill();
            
            // Draw + symbol
            ctx.strokeStyle = "#fff";
            ctx.lineWidth = 2;
            ctx.beginPath();
            const addCenterX = addButtonX + buttonSize / 2;
            const addCenterY = addButtonY + buttonSize / 2;
            ctx.moveTo(addCenterX - 6, addCenterY);
            ctx.lineTo(addCenterX + 6, addCenterY);
            ctx.moveTo(addCenterX, addCenterY - 6);
            ctx.lineTo(addCenterX, addCenterY + 6);
            ctx.stroke();
            
            // Check if there are dynamic inputs to show remove button
            const dynamicInputs = (this.inputs || []).filter(i => i.dynamic);
            if (dynamicInputs.length > 0) {
                // Draw remove button (-) on the right
                ctx.fillStyle = "#f44336"; // Red
                ctx.beginPath();
                ctx.roundRect(removeButtonX, removeButtonY, buttonSize, buttonSize, 3);
                ctx.fill();
                
                // Draw - symbol
                ctx.strokeStyle = "#fff";
                ctx.lineWidth = 2;
                ctx.beginPath();
                const removeCenterX = removeButtonX + buttonSize / 2;
                const removeCenterY = removeButtonY + buttonSize / 2;
                ctx.moveTo(removeCenterX - 6, removeCenterY);
                ctx.lineTo(removeCenterX + 6, removeCenterY);
                ctx.stroke();
            }
            
            ctx.restore();
            
            // Store button positions for mouse interaction
            this._dynamicButtons = {
                add: { x: addButtonX, y: addButtonY, width: buttonSize, height: buttonSize },
                remove: dynamicInputs.length > 0 ? 
                    { x: removeButtonX, y: removeButtonY, width: buttonSize, height: buttonSize } : null
            };
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
            
            // Position calculations - adjust for dynamic buttons if they exist
            const yOffset = this.supportsDynamicSockets ? 0 : 0; // Keep at bottom since buttons are now inside
            const bgX = this.size[0] - bgWidth - 7; // 5px from right edge
            const bgY = this.size[1] + yOffset; // Positioned at the bottom of the node
            
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

    // Handle mouse interactions for dynamic socket buttons and auto title
    // This is added to all nodes, but only active for those that support it
    NodeClass.prototype.onMouseDown = function(e, pos, graphcanvas) {
        // Check for dynamic button clicks first
        const hasDynamicSockets = this.supportsDynamicSockets || (this._definition && this._definition.supports_dynamic_sockets);
        if (hasDynamicSockets && this._dynamicButtons && pos) {
            const relativePos = [pos[0], pos[1]];
            
            // Check add button click
            const addBtn = this._dynamicButtons.add;
            if (addBtn && relativePos[0] >= addBtn.x && relativePos[0] <= addBtn.x + addBtn.width &&
                relativePos[1] >= addBtn.y && relativePos[1] <= addBtn.y + addBtn.height) {
                
                // Set flag to preserve width during this operation
                this._preserveWidthOnNextResize = true;
                // Add input slot (same logic as context menu)
                const count = (this.inputs || []).filter(i => i.dynamic).length;
                const socketType = convertSocketType(this.dynamicInputType);
                const socket = this.addInput(this.dynamicInputLabel.replace('{i}', count), socketType);
                socket.dynamic = true; // Mark as dynamic
                this.setDirtyCanvas(true, true);
                
                e.stopPropagation();
                e.preventDefault();
                return false;
            }
            
            // Check remove button click
            const removeBtn = this._dynamicButtons.remove;
            if (removeBtn && relativePos[0] >= removeBtn.x && relativePos[0] <= removeBtn.x + removeBtn.width &&
                relativePos[1] >= removeBtn.y && relativePos[1] <= removeBtn.y + removeBtn.height) {
                
                // Set flag to preserve width during this operation
                this._preserveWidthOnNextResize = true;
                // Remove last input slot (same logic as context menu)
                const dynamicInputs = (this.inputs || []).filter(i => i.dynamic);
                if (dynamicInputs.length > 0) {
                    const lastDynamic = dynamicInputs[dynamicInputs.length - 1];
                    const index = this.inputs.indexOf(lastDynamic);
                    this.removeInput(index);
                    this.setDirtyCanvas(true, true);
                }
                
                e.stopPropagation();
                e.preventDefault();
                return false;
            }
        }
        
        // Handle shift+mousedown to set automagic title if style.auto_title is set
        // auto_title will be a javascript format string that will be evaluated
        // e.g., "Custom Title ${node.properties.my_property}"
        if(this.autoTitleTemplate) {
            // Check if Shift key is pressed
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
    };

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
        
        // Clone dynamic input sockets (preserve order and indices)
        if (this.inputs && this.inputs.length) {
            for (var ii = 0; ii < this.inputs.length; ii++) {
                var input = this.inputs[ii];
                if (input && input.dynamic) {
                    var dynSocket = newNode.addInput(input.name, input.type);
                    if (dynSocket) {
                        dynSocket.dynamic = true;
                    }
                }
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

    NodeClass.prototype.getSlotMenuOptions = function(slot) {
        return []
    }

    // Override onAdded to ensure correct size when node is added to graph
    NodeClass.prototype.onAdded = function(graph) {
        // Call parent method if it exists
        if (LGraphNode.prototype.onAdded) {
            LGraphNode.prototype.onAdded.call(this, graph);
        }

        // Ensure node is at least wide enough for its title (and dynamic UI height if applicable)
        const correctSize = this.computeSize();
        // Grow width to fit title if needed
        if (correctSize[0] > this.size[0]) {
            this.size[0] = correctSize[0];
        }
        // Grow height to fit all widgets/content if needed
        if (correctSize[1] > this.size[1]) {
            this.size[1] = correctSize[1];
        }
    };

    return NodeClass;
}

// Add this function to your litegraphUtils.js
export function evaluateSimpleTemplate(template, node) {
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
        if(!definition.selectable) {
            continue;
        }
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

    // Ensure all widgets on the node become read-only when the node is locked
    if (node.widgets && node.widgets.length) {
        node.widgets.forEach(widget => {
            widget.readonly = true;
            widget.disabled = true; // Some widgets rely on this flag instead of readonly

            // Propagate the readonly flag to widget options if present
            if (widget.options) {
                widget.options.readonly = true;
                widget.options.disabled = true;
            }
        });

        // Force a redraw so the UI reflects the disabled state immediately
        if (node.graph && node.graph.list_of_graphcanvas && node.graph.list_of_graphcanvas.length > 0) {
            node.graph.list_of_graphcanvas[0].setDirty(true, true);
        }
    }

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
            
            // Handle dynamic sockets
            if (nodeData.dynamic_sockets?.inputs) {
                nodeData.dynamic_sockets.inputs.forEach(socketData => {
                    const socket = node.addInput(socketData.name, socketData.type);
                    socket.dynamic = true; // Mark as dynamic
                });
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
    // Deep-clone to avoid shared references with sceneNodes and reactive watchers
    graph.talemateProperties = graphData.properties ? JSON.parse(JSON.stringify(graphData.properties)) : {};
    graph.talemateFields = graphData.fields ? JSON.parse(JSON.stringify(graphData.fields)) : {};
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

/**
 * Vertically aligns selected nodes to the topmost node's y position.
 * @param {LGraphCanvas} canvas - The graph canvas instance
 * @returns {boolean} - Returns true if alignment was performed, false otherwise
 */
function handleVerticalAlignNodes(canvas) {
    if (!canvas.selected_nodes || Object.keys(canvas.selected_nodes).length < 2) {
        return false;
    }
    
    canvas.graph.beforeChange();
    
    // Find the topmost node (minimum y position)
    var topmostNode = null;
    var minY = Infinity;
    
    for (var id in canvas.selected_nodes) {
        var node = canvas.selected_nodes[id];
        if (node.pos[1] < minY) {
            minY = node.pos[1];
            topmostNode = node;
        }
    }
    
    // Align all selected nodes to the topmost node's y position
    if (topmostNode) {
        var targetY = topmostNode.pos[1];
        for (var id in canvas.selected_nodes) {
            var node = canvas.selected_nodes[id];
            if (node !== topmostNode) {
                node.pos[1] = targetY;
            }
        }
    }
    
    canvas.setDirty(true, true);
    canvas.graph.afterChange();
    return true;
}

/**
 * Horizontally aligns selected nodes to the leftmost node's x position.
 * @param {LGraphCanvas} canvas - The graph canvas instance
 * @returns {boolean} - Returns true if alignment was performed, false otherwise
 */
function handleHorizontalAlignNodes(canvas) {
    if (!canvas.selected_nodes || Object.keys(canvas.selected_nodes).length < 2) {
        return false;
    }
    
    canvas.graph.beforeChange();
    
    // Find the leftmost node (minimum x position)
    var leftmostNode = null;
    var minX = Infinity;
    
    for (var id in canvas.selected_nodes) {
        var node = canvas.selected_nodes[id];
        if (node.pos[0] < minX) {
            minX = node.pos[0];
            leftmostNode = node;
        }
    }
    
    // Align all selected nodes to the leftmost node's x position
    if (leftmostNode) {
        var targetX = leftmostNode.pos[0];
        for (var id in canvas.selected_nodes) {
            var node = canvas.selected_nodes[id];
            if (node !== leftmostNode) {
                node.pos[0] = targetX;
            }
        }
    }
    
    canvas.setDirty(true, true);
    canvas.graph.afterChange();
    return true;
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
    // W key - spawn Watch node when dragging connection from output
    else if (handleWatchNodeShortcut(this, e, key_code)) {
        block_default = true;
    }
    // S key - spawn SetState node when dragging connection from output
    else if (handleSetStateNodeShortcut(this, e, key_code)) {
        block_default = true;
    }
    // X key - spawn Stage node when dragging connection from output
    else if (handleStageNodeShortcut(this, e, key_code)) {
        block_default = true;
    }
    // Y key - vertically align selected nodes to the topmost node's y position
    else if (e.type == "keydown" && (key_code == 89 || key_code == 121) && !e.ctrlKey && !e.metaKey) {
        if (handleVerticalAlignNodes(this)) {
            block_default = true;
        }
    }
    // X key - horizontally align selected nodes to the leftmost node's x position
    else if (e.type == "keydown" && (key_code == 88 || key_code == 120) && !e.ctrlKey && !e.metaKey) {
        if (handleHorizontalAlignNodes(this)) {
            block_default = true;
        }
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

    // --- Single-node ALT+Drag clone logic ---
    // --- Single-node ALT+SHIFT Drag counterpart spawn logic ---
    if (e.altKey && e.shiftKey && e.which === 1 && (!this.selected_nodes || Object.keys(this.selected_nodes).length <= 1)) {
        const clickedNode = this.graph.getNodeOnPos(e.canvasX, e.canvasY);
        if (clickedNode && clickedNode.shiftCopy && this.allow_interaction && !this.read_only) {
            const { registry_name, copy_values } = clickedNode.shiftCopy || {};
            if (registry_name) {
                const counterpart = LiteGraph.createNode(registry_name);
                if (counterpart) {
                    // Position near the original
                    counterpart.pos = [clickedNode.pos[0] + 5, clickedNode.pos[1] + 5];

                    // Copy selected properties (supports both "key" and "source:target" formats)
                    if (Array.isArray(copy_values)) {
                        copy_values.forEach(entry => {
                            if (typeof entry !== 'string') { return; }
                            let sourceKey, targetKey;
                            const sepIndex = entry.indexOf(':');
                            if (sepIndex !== -1) {
                                sourceKey = entry.slice(0, sepIndex).trim();
                                targetKey = entry.slice(sepIndex + 1).trim() || sourceKey;
                            } else {
                                sourceKey = entry.trim();
                                targetKey = sourceKey;
                            }
                            if (sourceKey && clickedNode.properties && (sourceKey in clickedNode.properties)) {
                                const value = clickedNode.properties[sourceKey];
                                // Deep copy objects/arrays to avoid reference issues
                                counterpart.properties[targetKey] = (value && typeof value === 'object') ? JSON.parse(JSON.stringify(value)) : value;
                            }
                        });
                    }

                    // Sync widgets with copied properties
                    if (counterpart.widgets && counterpart.widgets.length) {
                        counterpart.widgets.forEach(widget => {
                            if (widget && widget.name && counterpart.properties.hasOwnProperty(widget.name)) {
                                widget.value = counterpart.properties[widget.name];
                            }
                        });
                    }

                    // Apply auto title immediately if available
                    if (counterpart.autoTitleTemplate) {
                        try {
                            const newTitle = evaluateSimpleTemplate(counterpart.autoTitleTemplate, counterpart);
                            counterpart.title = newTitle;
                        } catch (err) {
                            console.error("Error generating auto title for counterpart:", err);
                        }
                    }

                    // Add to graph and start dragging
                    this.graph.beforeChange();
                    this.graph.add(counterpart, false, { doCalcSize: false });
                    this.selectNode(counterpart, false);
                    if (this.allow_dragnodes) {
                        this.node_dragged = counterpart;
                    }

                    e.preventDefault();
                    e.stopPropagation();
                    return true;
                }
            }
        }
    }

    // --- Single-node ALT+Drag clone logic ---
    if (e.altKey && e.which === 1 && (!this.selected_nodes || Object.keys(this.selected_nodes).length <= 1)) {
        const clickedNode = this.graph.getNodeOnPos(e.canvasX, e.canvasY);
        if (clickedNode && this.allow_interaction && !this.read_only) {
            const cloned = clickedNode.clone();
            if (cloned) {
                cloned.pos[0] = clickedNode.pos[0] + 5;
                cloned.pos[1] = clickedNode.pos[1] + 5;
                this.graph.beforeChange();
                this.graph.add(cloned, false, { doCalcSize: false });
                
                // Select the cloned node and start dragging it
                this.selectNode(cloned, false);
                if (this.allow_dragnodes) {
                    this.node_dragged = cloned;
                }
                
                e.preventDefault();
                e.stopPropagation();
                return true;
            }
        }
    }

    // --- ALT+Drag when multiple nodes are selected but clicked node is NOT in the selection ---
    if (e.altKey && e.which === 1 && this.selected_nodes && Object.keys(this.selected_nodes).length > 1) {
        const clickedNode = this.graph.getNodeOnPos(e.canvasX, e.canvasY);
        if (clickedNode && !this.selected_nodes[clickedNode.id] && this.allow_interaction && !this.read_only) {
            const cloned = clickedNode.clone();
            if (cloned) {
                cloned.pos[0] = clickedNode.pos[0] + 5;
                cloned.pos[1] = clickedNode.pos[1] + 5;
                this.graph.beforeChange();
                this.graph.add(cloned, false, { doCalcSize: false });
                // Select the cloned node and start dragging it
                this.selectNode(cloned, false);
                if (this.allow_dragnodes) {
                    this.node_dragged = cloned;
                }
                e.preventDefault();
                e.stopPropagation();
                return true;
            }
        }
    }

    // --- Multi-node ALT+Drag clone logic ---
    if (e.altKey && e.which === 1 && this.selected_nodes && Object.keys(this.selected_nodes).length > 1) {
        // If the cursor is over one of the currently selected nodes
        const clickedNode = this.graph.getNodeOnPos(e.canvasX, e.canvasY);
        if (clickedNode && this.selected_nodes[clickedNode.id]) {
            // Prepare history action
            this.graph.beforeChange();

            const selectedList = Object.values(this.selected_nodes);
            const clonedNodes = [];
            const idMap = {};

            // First pass – clone every selected node
            selectedList.forEach(originalNode => {
                const clone = originalNode.clone();
                clone.pos = [originalNode.pos[0], originalNode.pos[1]]; // same position, will move during drag
                this.graph.add(clone);
                clonedNodes.push(clone);
                idMap[originalNode.id] = clone.id;
                if (originalNode.talemateId) {
                    idMap[originalNode.talemateId] = clone.talemateId || clone.id;
                }
            });

            // Second pass – recreate internal connections between the cloned nodes
            selectedList.forEach(originalNode => {
                if (!originalNode.outputs) return;
                originalNode.outputs.forEach((output, outputIdx) => {
                    if (!output.links) return;
                    output.links.forEach(linkId => {
                        const linkInfo = this.graph.links[linkId];
                        if (!linkInfo) return;
                        const targetId = linkInfo.target_id;
                        if (!this.selected_nodes[targetId]) return; // only duplicate connections within the selection
                        const newOrigin = this.graph.getNodeById(idMap[originalNode.id]);
                        const newTarget = this.graph.getNodeById(idMap[targetId]);
                        if (newOrigin && newTarget) {
                            newOrigin.connect(outputIdx, newTarget, linkInfo.target_slot);
                        }
                    });
                });
            });

            // Replace selection with the cloned nodes
            this.selectNodes(clonedNodes);

            // Store drag info so we can move the clones while the pointer moves
            this._cloning_multi_drag = {
                active: true,
                clones: clonedNodes,
                lastX: e.clientX,
                lastY: e.clientY
            };

            // Block default handler (which would clone only one node)
            e.preventDefault();
            e.stopPropagation();
            return true;
        }
    }

    // If no custom logic handled the click, proceed with the original logic
    return original_processMouseDown.call(this, e);
};

// Preserve references to the original handlers
const original_processMouseMove = LGraphCanvas.prototype.processMouseMove;
const original_processMouseUp = LGraphCanvas.prototype.processMouseUp;

// Override processMouseMove to move the duplicated selection while dragging
LGraphCanvas.prototype.processMouseMove = function(e) {
    if (this._cloning_multi_drag && this._cloning_multi_drag.active) {
        this.adjustMouseEvent(e);
        const info = this._cloning_multi_drag;
        const dxClient = e.clientX - info.lastX;
        const dyClient = e.clientY - info.lastY;
        if (dxClient !== 0 || dyClient !== 0) {
            const dxGraph = dxClient / this.ds.scale;
            const dyGraph = dyClient / this.ds.scale;
            info.clones.forEach(node => {
                node.pos[0] += dxGraph;
                node.pos[1] += dyGraph;
            });
            info.lastX = e.clientX;
            info.lastY = e.clientY;
            this.setDirty(true, true);
        }
        e.preventDefault();
        e.stopPropagation();
        return true;
    }
    return original_processMouseMove.call(this, e);
};

// Override processMouseUp to finish the drag operation and register history
LGraphCanvas.prototype.processMouseUp = function(e) {
    if (this._cloning_multi_drag && this._cloning_multi_drag.active) {
        this._cloning_multi_drag.active = false;
        delete this._cloning_multi_drag;
        this.graph.afterChange();
        e.preventDefault();
        e.stopPropagation();
        return true;
    }
    return original_processMouseUp.call(this, e);
};

