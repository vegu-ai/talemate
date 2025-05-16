// exportGraph.js

// Convert LiteGraph graph back to JSON format
export function convertGraphToJSON(graph) {
    const nodes = [];
    const connections = [];
    const comments = [];

    // set talemateId for each node
    for (const node of graph._nodes) {
        // if node.id is already a uuid, use it
        // node.id can also be a number, which is not a valid uuid for the backend
        // so we need to generate a new one
        if(node.talemateId) {
            continue;
        } else if(new String(node.id).length === 36) {
            node.talemateId = node.id;
        } else {
            node.talemateId = crypto.randomUUID();
        }
    }

    // Process all nodes in the graph
    for (const node of graph._nodes) {
        // Skip inherited nodes when converting back to JSON
        if (node.inherited === true) {
            continue;
        }
        
        if (node.type === "core/Comment") {
            comments.push({
                text: node.properties.text,
                x: Math.round(node.pos[0]),
                y: Math.round(node.pos[1]),
                width: Math.round(node.size[0])
            });
            continue; // Skip adding comment nodes to the regular nodes list
        }

        // Create basic node structure
        const nodeData = {
            id: node.talemateId,
            registry: node.type,
            properties: { ...node.properties },
            x: Math.round(node.pos[0]),
            y: Math.round(node.pos[1]),
            width: Math.round(node.size[0]),
            height: Math.round(node.size[1]),
            parent: null,
            title: node.title,
            collapsed: node.flags.collapsed,
        };
        
        // Clean up properties
        // Remove undefined/null values and handle special cases
        Object.keys(nodeData.properties).forEach(key => {
            if (nodeData.properties[key] === undefined) {
                delete nodeData.properties[key];
            }
        });
        
        // If properties is empty, keep it as an empty object
        if (Object.keys(nodeData.properties).length === 0) {
            nodeData.properties = {};
        }
        
        nodes.push(nodeData);
        
        // Process connections for this node
        if (node.outputs) {
            node.outputs.forEach((output) => {
                if (output.links) {
                    output.links.forEach(linkId => {
                        const link = graph.links[linkId];
                        if (link) {
                            const targetNode = graph._nodes_by_id[link.target_id];
                            if (targetNode && !targetNode.inherited) {
                                const connection = {
                                    from: `${node.talemateId}.${output.name}`,
                                    to: `${targetNode.talemateId}.${targetNode.inputs[link.target_slot].name}`
                                };
                                connections.push(connection);
                            }
                        }
                    });
                }
            });
        }
    }

    const groups = []

    // process all groups in the graph
    for(const group of graph._groups) {

        if(group.inherited) {
            continue;
        }

        groups.push({
            title: group.title,
            color: group.color,
            x: parseInt(group.pos[0]),
            y: parseInt(group.pos[1]),
            width: parseInt(group.size[0]),
            height: parseInt(group.size[1]),
            font_size: group.font_size,
        })
    }
    
    // Sort nodes and connections for consistency
    //nodes.sort((a, b) => a.id.localeCompare(b.id));
    //connections.sort((a, b) => {
    //    const fromCompare = a.from.localeCompare(b.from);
    //    if (fromCompare !== 0) return fromCompare;
    //    return a.to.localeCompare(b.to);
    //});
    
    return {
        nodes,
        connections,
        comments,
        groups,
        properties: graph.talemateProperties,
        registry: graph.talemateRegistry,
        extends: graph.talemateExtends,
    };
}

// Export only selected nodes with their connections and identifying external inputs/outputs
export function convertSelectedGraphToJSON(graph, selectedNodes) {

    if(!selectedNodes || Object.keys(selectedNodes).length === 0) {
        return null;
    }

    const nodes = [];
    const connections = [];
    const comments = [];
    const inputs = [];
    const outputs = [];
    
    // Set to track unique connections
    const uniqueConnections = new Set();
    
    // Create a map of selected nodes for quick lookup
    const selectedNodeMap = {};
    Object.values(selectedNodes).forEach(node => {
        selectedNodeMap[node.id] = true;
        // Also map by talemateId if available
        if (node.talemateId) {
            selectedNodeMap[node.talemateId] = true;
        }
    });
    
    // Ensure all nodes have talemateId
    for (const node of Object.values(selectedNodes)) {
        if (!node.talemateId) {
            if (new String(node.id).length === 36) {
                node.talemateId = node.id;
            } else {
                node.talemateId = crypto.randomUUID();
            }
        }
    }
    
    // Find the top-left most position to normalize coordinates
    let minX = Infinity;
    let minY = Infinity;
    
    for (const node of Object.values(selectedNodes)) {
        if (node.type !== "core/Comment" && !node.inherited) {
            minX = Math.min(minX, node.pos[0]);
            minY = Math.min(minY, node.pos[1]);
        }
    }
    
    // Process selected nodes
    for (const node of Object.values(selectedNodes)) {
        // Skip inherited nodes
        if (node.inherited === true) {
            continue;
        }
        
        if (node.type === "core/Comment") {
            comments.push({
                text: node.properties.text,
                x: Math.round(node.pos[0] - minX),
                y: Math.round(node.pos[1] - minY),
                width: Math.round(node.size[0])
            });
            continue; // Skip adding comment nodes to the regular nodes list
        }
        
        // Create basic node structure with normalized coordinates
        const nodeData = {
            id: node.talemateId,
            registry: node.type,
            properties: { ...node.properties },
            x: Math.round(node.pos[0] - minX),
            y: Math.round(node.pos[1] - minY),
            width: Math.round(node.size[0]),
            height: Math.round(node.size[1]),
            parent: null,
            title: node.title,
            collapsed: node.flags.collapsed,
        };
        
        // Clean up properties
        Object.keys(nodeData.properties).forEach(key => {
            if (nodeData.properties[key] === undefined) {
                delete nodeData.properties[key];
            }
        });
        
        // If properties is empty, keep it as an empty object
        if (Object.keys(nodeData.properties).length === 0) {
            nodeData.properties = {};
        }
        
        nodes.push(nodeData);
        
        // Process connections and track external inputs/outputs
        // Check inputs for external connections
        if (node.inputs) {
            node.inputs.forEach((input, inputIndex) => {
                if (input.link) {
                    const link = graph.links[input.link];
                    if (link) {
                        const sourceNode = graph._nodes_by_id[link.origin_id];
                        if (sourceNode) {
                            // If source node is selected, this is an internal connection
                            if (selectedNodeMap[sourceNode.id] || 
                                (sourceNode.talemateId && selectedNodeMap[sourceNode.talemateId])) {
                                
                                const connection = {
                                    from: `${sourceNode.talemateId}.${sourceNode.outputs[link.origin_slot].name}`,
                                    to: `${node.talemateId}.${input.name}`
                                };
                                
                                // Only add connection if it's not a duplicate
                                const connectionKey = `${connection.from}|${connection.to}`;
                                if (!uniqueConnections.has(connectionKey)) {
                                    uniqueConnections.add(connectionKey);
                                    connections.push(connection);
                                }
                            } 
                            // If source node is not selected, this is an external input
                            else {
                                inputs.push({
                                    title: input.name,
                                    type: input.type,
                                    nodeId: node.talemateId,
                                    socketIndex: inputIndex
                                });
                            }
                        }
                    }
                }
            });
        }
        
        // Check outputs for external connections
        if (node.outputs) {
            node.outputs.forEach((output, outputIndex) => {
                if (output.links && output.links.length > 0) {
                    let hasExternalOutput = false;
                    
                    output.links.forEach(linkId => {
                        const link = graph.links[linkId];
                        if (link) {
                            const targetNode = graph._nodes_by_id[link.target_id];
                            if (targetNode) {
                                // If target node is selected, this is an internal connection
                                if (selectedNodeMap[targetNode.id] || 
                                    (targetNode.talemateId && selectedNodeMap[targetNode.talemateId])) {
                                    
                                    const connection = {
                                        from: `${node.talemateId}.${output.name}`,
                                        to: `${targetNode.talemateId}.${targetNode.inputs[link.target_slot].name}`
                                    };
                                    
                                    // Only add connection if it's not a duplicate
                                    const connectionKey = `${connection.from}|${connection.to}`;
                                    if (!uniqueConnections.has(connectionKey)) {
                                        uniqueConnections.add(connectionKey);
                                        connections.push(connection);
                                    }
                                } 
                                // If target node is not selected and we haven't added this output yet
                                else if (!hasExternalOutput) {
                                    outputs.push({
                                        title: output.name,
                                        type: output.type,
                                        nodeId: node.talemateId,
                                        socketIndex: outputIndex
                                    });
                                    hasExternalOutput = true; // Only add the first external output
                                }
                            }
                        }
                    });
                }
            });
        }
    }
    
    // Process selected comments (if any are in the selection)
    const selectedComments = Object.values(selectedNodes).filter(node => node.type === "core/Comment");
    for (const comment of selectedComments) {
        comments.push({
            text: comment.properties.text,
            x: Math.round(comment.pos[0] - minX),
            y: Math.round(comment.pos[1] - minY),
            width: Math.round(comment.size[0])
        });
    }
    
    // Create Input and Output nodes based on the detected external connections
    const inputNodes = [];
    const outputNodes = [];
    const newConnections = [];
    
    // Find the leftmost and rightmost X coordinates from existing nodes
    if (nodes.length > 0) {
        const left_x = 0; // We already normalized, so leftmost is at 0
        const right_x = Math.max(...nodes.map(node => node.x + node.width));
        const top_y = 0;   // We already normalized, so topmost is at 0
        
        // Create Input nodes
        inputs.forEach((input, index) => {
            const input_id = crypto.randomUUID();
            const input_type = (input.type == "*" || !input.type) ? "any" : input.type;
            const input_title = input.title || `input_${index}`;
            
            // Position input nodes to the left of the existing nodes
            const inputNode = {
                id: input_id,
                registry: "core/Input",
                properties: {
                    input_type: input_type,
                    input_name: input_title,
                    input_optional: false,
                    input_group: "",
                    num: index
                },
                x: left_x - 250,  // Position to the left
                y: top_y + (index * 200),       // Stack vertically with spacing
                width: 210,
                height: 154,
                parent: null,
                title: `IN ${input_title}`,
                collapsed: false
            };
            
            inputNodes.push(inputNode);
            
            // Create a connection from this input node to the target node
            if (input.nodeId && input.title) {
                newConnections.push({
                    from: `${input_id}.value`,
                    to: `${input.nodeId}.${input.title}`
                });
            }
        });
        
        // Create Output nodes
        outputs.forEach((output, index) => {
            const output_id = crypto.randomUUID();
            const output_type = (output.type == "*" || !output.type) ? "any" : output.type;
            const output_title = output.title || `output_${index}`;
            
            // Position output nodes to the right of the existing nodes
            const outputNode = {
                id: output_id,
                registry: "core/Output",
                properties: {
                    output_type: output_type,
                    output_name: output_title,
                    num: index
                },
                x: right_x + 60,           // Position to the right
                y: top_y + (index * 80),   // Stack vertically with spacing
                width: 210,
                height: 154,
                parent: null,
                title: `OUT ${output_title}`,
                collapsed: false
            };
            
            outputNodes.push(outputNode);
            
            // Create a connection from the source node to this output
            if (output.nodeId && output.title) {
                newConnections.push({
                    from: `${output.nodeId}.${output.title}`,
                    to: `${output_id}.value`
                });
            }
        });
    }
    
    // Add the Input and Output nodes to the node list
    nodes.push(...inputNodes);
    nodes.push(...outputNodes);
    
    // Add the new connections to the connections list
    connections.push(...newConnections);
    
    // Don't include the inputs/outputs arrays in the result since we've created actual nodes
    return {
        nodes,
        connections,
        comments,
        groups: [], // No groups for selection export
        properties: {}, // Empty properties for new module
        registry: null, // No registry for selection
        extends: null, // No extends for selection
    };
}

// Helper function to convert entire graph structure
export function convertFullGraphToJSON(graph) {
    return {
        graph: convertGraphToJSON(graph)
    };
} 