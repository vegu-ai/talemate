// graphConnectionUtil.js
import { LiteGraph } from 'litegraph.js';
import { evaluateSimpleTemplate } from './litegraphUtils.js';

/**
 * Retrieves a name value from a source node.
 * If the output socket name is "value", checks properties/widgets first (input_name, name, attribute),
 * then falls back to the socket name.
 * If the output socket name is anything else, always uses the socket name directly.
 * @param {LGraphNode} sourceNode - The source node to check for properties
 * @param {Object} connectingOutput - The output socket being connected from
 * @returns {string} - The name value to use
 */
function getNameFromSourceNode(sourceNode, connectingOutput) {
    var outputSocketName = connectingOutput.name || connectingOutput.label || "value";
    
    // If the socket name is not "value", always use the socket name directly
    if (outputSocketName !== "value") {
        return outputSocketName;
    }
    
    // Only check properties/widgets if the socket name is "value"
    var nameValue = null;
    
    // Helper function to get value from properties or widgets
    function getPropertyValue(key) {
        // First check properties
        if (sourceNode.properties && sourceNode.properties[key] !== undefined && sourceNode.properties[key] !== null) {
            return sourceNode.properties[key];
        }
        // Fallback to widgets
        if (sourceNode.widgets) {
            var widget = sourceNode.widgets.find(function(w) {
                return w.name === key;
            });
            if (widget && widget.value !== undefined && widget.value !== null) {
                return widget.value;
            }
        }
        return null;
    }
    
    // Check in order: input_name, name, attribute, property_name
    nameValue = getPropertyValue("input_name");
    if (nameValue === null) {
        nameValue = getPropertyValue("name");
    }
    if (nameValue === null) {
        nameValue = getPropertyValue("attribute");
    }
    if (nameValue === null) {
        nameValue = getPropertyValue("property_name");
    }
    // Fall back to output socket name if no property was found
    if (nameValue === null) {
        nameValue = outputSocketName;
    }
    
    return nameValue;
}

/**
 * Generic handler for creating a node from a connection shortcut.
 * @param {LGraphCanvas} canvas - The graph canvas instance
 * @param {KeyboardEvent} e - The keyboard event
 * @param {number} key_code - The key code from the event
 * @param {Object} config - Configuration object
 * @param {number[]} config.keyCodes - Array of key codes to match (uppercase and lowercase)
 * @param {string} config.nodeType - The type of node to create (e.g., "core/Watch")
 * @param {string} config.inputSocketName - Name of the input socket to connect to (e.g., "value", "state")
 * @param {Function} config.configureNode - Function to configure the node after creation
 * @returns {boolean} - Returns true if the event was handled, false otherwise
 */
function handleNodeShortcut(canvas, e, key_code, config) {
    var keyCodes = config.keyCodes;
    var nodeType = config.nodeType;
    var inputSocketName = config.inputSocketName;
    var configureNode = config.configureNode;
    
    // Check if the key was pressed without modifiers
    var keyMatches = keyCodes.some(function(kc) { return key_code === kc; });
    if (e.type === "keydown" && keyMatches && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) {
        // Check if we're currently dragging a connection from an output
        if (canvas.connecting_node && canvas.connecting_output && canvas.connecting_slot !== undefined) {
            // Prevent default behavior
            e.preventDefault();
            e.stopPropagation();
            
            // Create the node
            var newNode = LiteGraph.createNode(nodeType);
            if (newNode) {
                canvas.graph.beforeChange();
                
                // Configure the node (set properties, widgets, title, etc.)
                if (configureNode) {
                    configureNode(newNode, canvas);
                }
                
                // Position the node near the mouse cursor
                var mousePos = canvas.last_mouse_position || [
                    canvas.canvas.width * 0.5,
                    canvas.canvas.height * 0.5
                ];
                var canvasPos = canvas.convertCanvasToOffset(mousePos);
                newNode.pos = [canvasPos[0], canvasPos[1]];
                
                // Add the node to the graph
                canvas.graph.add(newNode);
                
                // Find the input socket index
                var inputIndex = 0;
                if (newNode.inputs && newNode.inputs.length > 0) {
                    var targetInput = newNode.inputs.find(function(input) {
                        return input.name === inputSocketName;
                    });
                    if (targetInput) {
                        inputIndex = newNode.inputs.indexOf(targetInput);
                    }
                }
                
                // Connect the output to the node's input
                canvas.connecting_node.connect(canvas.connecting_slot, newNode, inputIndex);
                
                // Clear the connecting state to complete the connection
                canvas.connecting_output = null;
                canvas.connecting_input = null;
                canvas.connecting_node = null;
                canvas.connecting_slot = -1;
                canvas.connecting_pos = null;
                
                // Mark canvas as dirty and register change
                canvas.setDirty(true, true);
                canvas.graph.afterChange();
                
                return true; // Event was handled
            }
        }
    }
    
    return false; // Event was not handled
}

/**
 * Helper function to set a property and widget value on a node.
 * @param {LGraphNode} node - The node to configure
 * @param {string} propertyName - The name of the property/widget to set
 * @param {*} value - The value to set
 */
function setNodePropertyAndWidget(node, propertyName, value) {
    node.setProperty(propertyName, value);
    if (node.widgets) {
        var widget = node.widgets.find(function(w) {
            return w.name === propertyName;
        });
        if (widget) {
            widget.value = value;
        }
    }
}

/**
 * Helper function to apply auto title template if available.
 * @param {LGraphNode} node - The node to apply the title to
 */
function applyAutoTitle(node) {
    if (node.autoTitleTemplate) {
        try {
            const newTitle = evaluateSimpleTemplate(node.autoTitleTemplate, node);
            node.title = newTitle;
        } catch (error) {
            console.error("Error generating auto title for " + node.type + " node:", error);
        }
    }
}

/**
 * Handles the W keypress shortcut to spawn a Watch node when dragging a connection from an output.
 * @param {LGraphCanvas} canvas - The graph canvas instance
 * @param {KeyboardEvent} e - The keyboard event
 * @param {number} key_code - The key code from the event
 * @returns {boolean} - Returns true if the event was handled, false otherwise
 */
export function handleWatchNodeShortcut(canvas, e, key_code) {
    return handleNodeShortcut(canvas, e, key_code, {
        keyCodes: [87, 119], // W, w
        nodeType: "core/Watch",
        inputSocketName: "value",
        configureNode: function(node, canvas) {
            var nameValue = getNameFromSourceNode(canvas.connecting_node, canvas.connecting_output);
            node.title = nameValue;
        }
    });
}

/**
 * Handles the S keypress shortcut to spawn a SetState node when dragging a connection from an output.
 * @param {LGraphCanvas} canvas - The graph canvas instance
 * @param {KeyboardEvent} e - The keyboard event
 * @param {number} key_code - The key code from the event
 * @returns {boolean} - Returns true if the event was handled, false otherwise
 */
export function handleSetStateNodeShortcut(canvas, e, key_code) {
    return handleNodeShortcut(canvas, e, key_code, {
        keyCodes: [83, 115], // S, s
        nodeType: "state/SetState",
        inputSocketName: "value",
        configureNode: function(node, canvas) {
            var nameValue = getNameFromSourceNode(canvas.connecting_node, canvas.connecting_output);
            setNodePropertyAndWidget(node, "name", nameValue);
            applyAutoTitle(node);
        }
    });
}

/**
 * Handles the X keypress shortcut to spawn a Stage node when dragging a connection from an output.
 * The new Stage node will have its stage value set to the highest existing stage value + 1.
 * @param {LGraphCanvas} canvas - The graph canvas instance
 * @param {KeyboardEvent} e - The keyboard event
 * @param {number} key_code - The key code from the event
 * @returns {boolean} - Returns true if the event was handled, false otherwise
 */
export function handleStageNodeShortcut(canvas, e, key_code) {
    return handleNodeShortcut(canvas, e, key_code, {
        keyCodes: [88, 120], // X, x
        nodeType: "core/Stage",
        inputSocketName: "state",
        configureNode: function(node, canvas) {
            // Find all existing Stage nodes in the graph and get the highest stage value
            var maxStage = -1;
            if (canvas.graph && canvas.graph._nodes) {
                canvas.graph._nodes.forEach(function(existingNode) {
                    if (existingNode.type === "core/Stage" && existingNode.properties && existingNode.properties.stage !== undefined && existingNode.properties.stage !== null) {
                        var stageValue = parseInt(existingNode.properties.stage, 10);
                        if (!isNaN(stageValue) && stageValue > maxStage) {
                            maxStage = stageValue;
                        }
                    }
                });
            }
            
            // Set the stage value to highest + 1 (or 0 if no stages exist)
            var newStageValue = maxStage + 1;
            setNodePropertyAndWidget(node, "stage", newStageValue);
            applyAutoTitle(node);
        }
    });
}

