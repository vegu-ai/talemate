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
    
    // Check in order: input_name, name, attribute
    nameValue = getPropertyValue("input_name");
    if (nameValue === null) {
        nameValue = getPropertyValue("name");
    }
    if (nameValue === null) {
        nameValue = getPropertyValue("attribute");
    }
    
    // Fall back to output socket name if no property was found
    if (nameValue === null) {
        nameValue = outputSocketName;
    }
    
    return nameValue;
}

/**
 * Handles the W keypress shortcut to spawn a Watch node when dragging a connection from an output.
 * @param {LGraphCanvas} canvas - The graph canvas instance
 * @param {KeyboardEvent} e - The keyboard event
 * @param {number} key_code - The key code from the event
 * @returns {boolean} - Returns true if the event was handled, false otherwise
 */
export function handleWatchNodeShortcut(canvas, e, key_code) {
    // Check if W key was pressed (87 = W, 119 = w) without modifiers
    if (e.type === "keydown" && (key_code === 87 || key_code === 119) && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) {
        // Check if we're currently dragging a connection from an output
        if (canvas.connecting_node && canvas.connecting_output && canvas.connecting_slot !== undefined) {
            // Prevent default behavior
            e.preventDefault();
            e.stopPropagation();
            
            // Create Watch node
            var watchNode = LiteGraph.createNode("core/Watch");
            if (watchNode) {
                canvas.graph.beforeChange();
                
                // Get the name for the title using the shared name retrieval logic
                var nameValue = getNameFromSourceNode(canvas.connecting_node, canvas.connecting_output);
                watchNode.title = nameValue;
                
                // Position the Watch node near the mouse cursor
                var mousePos = canvas.last_mouse_position || [
                    canvas.canvas.width * 0.5,
                    canvas.canvas.height * 0.5
                ];
                var canvasPos = canvas.convertCanvasToOffset(mousePos);
                watchNode.pos = [canvasPos[0], canvasPos[1]];
                
                // Add the node to the graph
                canvas.graph.add(watchNode);
                
                // Connect the output to the Watch node's input
                // Find the "value" input socket index
                var watchInputIndex = 0;
                if (watchNode.inputs && watchNode.inputs.length > 0) {
                    var valueInput = watchNode.inputs.find(function(input) {
                        return input.name === "value";
                    });
                    if (valueInput) {
                        watchInputIndex = watchNode.inputs.indexOf(valueInput);
                    }
                }
                canvas.connecting_node.connect(canvas.connecting_slot, watchNode, watchInputIndex);
                
                // Clear the connecting state to complete the connection
                // Need to clear all connecting-related properties to prevent drawing errors
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
 * Handles the S keypress shortcut to spawn a SetState node when dragging a connection from an output.
 * @param {LGraphCanvas} canvas - The graph canvas instance
 * @param {KeyboardEvent} e - The keyboard event
 * @param {number} key_code - The key code from the event
 * @returns {boolean} - Returns true if the event was handled, false otherwise
 */
export function handleSetStateNodeShortcut(canvas, e, key_code) {
    // Check if S key was pressed (83 = S, 115 = s) without modifiers
    if (e.type === "keydown" && (key_code === 83 || key_code === 115) && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) {
        // Check if we're currently dragging a connection from an output
        if (canvas.connecting_node && canvas.connecting_output && canvas.connecting_slot !== undefined) {
            // Prevent default behavior
            e.preventDefault();
            e.stopPropagation();
            
            // Create SetState node
            var setStateNode = LiteGraph.createNode("state/SetState");
            if (setStateNode) {
                canvas.graph.beforeChange();
                
                // Get the name value using the shared name retrieval logic
                var nameValue = getNameFromSourceNode(canvas.connecting_node, canvas.connecting_output);
                
                // Set the name property
                setStateNode.setProperty("name", nameValue);
                // Also update the widget if it exists
                if (setStateNode.widgets) {
                    var nameWidget = setStateNode.widgets.find(function(widget) {
                        return widget.name === "name";
                    });
                    if (nameWidget) {
                        nameWidget.value = nameValue;
                    }
                }
                
                // Apply auto title if available
                if (setStateNode.autoTitleTemplate) {
                    try {
                        const newTitle = evaluateSimpleTemplate(setStateNode.autoTitleTemplate, setStateNode);
                        setStateNode.title = newTitle;
                    } catch (error) {
                        console.error("Error generating auto title for SetState node:", error);
                    }
                }
                
                // Position the SetState node near the mouse cursor
                var mousePos = canvas.last_mouse_position || [
                    canvas.canvas.width * 0.5,
                    canvas.canvas.height * 0.5
                ];
                var canvasPos = canvas.convertCanvasToOffset(mousePos);
                setStateNode.pos = [canvasPos[0], canvasPos[1]];
                
                // Add the node to the graph
                canvas.graph.add(setStateNode);
                
                // Connect the output to the SetState node's value input
                // Find the "value" input socket index
                var valueInputIndex = 0;
                if (setStateNode.inputs && setStateNode.inputs.length > 0) {
                    var valueInput = setStateNode.inputs.find(function(input) {
                        return input.name === "value";
                    });
                    if (valueInput) {
                        valueInputIndex = setStateNode.inputs.indexOf(valueInput);
                    }
                }
                canvas.connecting_node.connect(canvas.connecting_slot, setStateNode, valueInputIndex);
                
                // Clear the connecting state to complete the connection
                // Need to clear all connecting-related properties to prevent drawing errors
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

