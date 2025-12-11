import { LiteGraph, LGraphCanvas } from 'litegraph.js';

const GROUP_DISTANCE_TOLERANCE = 500;
const GROUP_SPACING = 3;

/**
 * Gets the effective size of a node, accounting for collapsed state.
 * When collapsed, nodes only take up the title bar height.
 * @param {LGraphNode} node The node to get the effective size for.
 * @returns {number[]} [width, height] - The effective size of the node.
 */
function getEffectiveNodeSize(node) {
    if (node.flags && node.flags.collapsed) {
        // When collapsed, use title bar height
        // Width can use collapsed width if available, otherwise use current width
        const width = node._collapsed_width || node.size[0];
        const height = LiteGraph.NODE_TITLE_HEIGHT;
        return [width, height];
    }
    // When expanded, use the actual size
    return [node.size[0], node.size[1]];
}

/**
 * Fits the group boundaries snugly around its contained nodes, adding padding.
 * Triggered by Ctrl+Clicking the group title.
 * @param {LGraphGroup} group The group to resize.
 * @param {LGraphCanvas} canvas The canvas instance.
 */
export function handleFitGroupToNodes(group, canvas) {
    group.recomputeInsideNodes(); // Make sure group._nodes is up-to-date

    if (!group._nodes.length) {
        return false; // Nothing to fit to
    }

    canvas.graph.beforeChange();

    // Calculate bounding box of nodes within the group
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const node of group._nodes) {
        const [nodeWidth, nodeHeight] = getEffectiveNodeSize(node);
        minX = Math.min(minX, node.pos[0]);
        minY = Math.min(minY, node.pos[1]);
        maxX = Math.max(maxX, node.pos[0] + nodeWidth);
        maxY = Math.max(maxY, node.pos[1] + nodeHeight);
    }

    // Constants for padding and title height
    const padding = 25;
    const titleHeight = LiteGraph.NODE_TITLE_HEIGHT+padding;

    // Calculate the desired top-left corner for the nodes area within the group
    const targetNodesAreaX = group.pos[0] + padding;
    const targetNodesAreaY = group.pos[1] + titleHeight + padding;

    // Calculate the offset needed to move the nodes
    const offsetX = targetNodesAreaX - minX;
    const offsetY = targetNodesAreaY - minY;

    // Reposition nodes
    for (const node of group._nodes) {
        node.pos[0] += offsetX;
        node.pos[1] += offsetY;
    }

    // Calculate new group size based on the moved nodes and padding
    // New max X/Y is the original max X/Y plus the offset
    const newNodesMaxX = maxX + offsetX;
    const newNodesMaxY = maxY + offsetY;
    // Width/Height is the distance from the group's top-left to the new nodes' bottom-right, plus padding
    const newGroupWidth = newNodesMaxX - group.pos[0] + padding;
    const newGroupHeight = newNodesMaxY - group.pos[1] + padding;

    // Apply new size (with minimums)
    group.size = [Math.max(140, newGroupWidth), Math.max(80, newGroupHeight)];
    canvas.graph.afterChange();
    canvas.setDirty(true, true);

    return true; // Indicate the event was handled
}

/**
 * Creates a new group that encompasses all selected nodes.
 * @param {LGraphCanvas} canvas The canvas instance with selected nodes.
 * @returns {boolean} True if a group was created, false otherwise.
 */
export function handleCreateGroupFromSelectedNodes(canvas, options = {}) {
    const { colorKey, title } = options || {};
    // Check if we have selected nodes
    if (!canvas.selected_nodes || Object.keys(canvas.selected_nodes).length === 0) {
        return false; // No nodes selected
    }

    canvas.graph.beforeChange();

    // Calculate bounding box of all selected nodes
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    const selectedNodes = Object.values(canvas.selected_nodes);
    
    for (const node of selectedNodes) {
        const [nodeWidth, nodeHeight] = getEffectiveNodeSize(node);
        minX = Math.min(minX, node.pos[0]);
        minY = Math.min(minY, node.pos[1]);
        maxX = Math.max(maxX, node.pos[0] + nodeWidth);
        maxY = Math.max(maxY, node.pos[1] + nodeHeight);
    }

    // Constants for padding and title height
    const padding = 25;
    const titleHeight = LiteGraph.NODE_TITLE_HEIGHT;
    const topPadding = padding + 20; // Extra top padding

    // Create the new group with proper dimensions
    const new_group = new LiteGraph.LGraphGroup();
    new_group.title = title || "Group"; // Default or provided title
    
    // Apply color preset if provided
    if (colorKey && LGraphCanvas && LGraphCanvas.node_colors && LGraphCanvas.node_colors[colorKey]) {
        const preset = LGraphCanvas.node_colors[colorKey];
        if (preset && preset.groupcolor) {
            new_group.color = preset.groupcolor;
        }
    }
    
    // Position and size the group to encompass the nodes plus padding
    new_group.pos = [minX - padding, minY - topPadding - titleHeight];
    
    // Width/height calculation (add padding on both sides)
    const width = (maxX - minX) + (padding * 2);
    const height = (maxY - minY) + padding + topPadding + titleHeight;
    
    // Apply size (with minimums)
    new_group.size = [Math.max(140, width), Math.max(80, height)];
    
    // Add the group to the graph
    canvas.graph.add(new_group);
    
    // Add the nodes to the group
    for (const node of selectedNodes) {
        new_group._nodes.push(node);
    }
    
    canvas.graph.afterChange();
    canvas.setDirty(true, true);
    
    // Deselect nodes after creating the group (use canvas API to clear visual highlights)
    if (typeof canvas.deselectAllNodes === 'function') {
        canvas.deselectAllNodes();
    }
    
    return true; // Indicate the event was handled
}

/**
 * Snaps the given group vertically to the closest group above it if within tolerance.
 * Triggered by Alt+Clicking the group title.
 * @param {LGraphGroup} group The group to snap.
 * @param {LGraphCanvas} canvas The canvas instance.
 */
export function handleVerticalSnapGroup(group, canvas) {
    canvas.graph.beforeChange();

    const snapTolerance = GROUP_DISTANCE_TOLERANCE;
    const snapSpacing = GROUP_SPACING; // Vertical space between snapped groups
    let closestGroupAbove = null;
    let minVerticalDistance = snapTolerance + 1; // Initialize higher than tolerance

    const groupX1 = group.pos[0];
    const groupY1 = group.pos[1];
    const groupX2 = group.pos[0] + group.size[0];

    for (const otherGroup of canvas.graph._groups) {
        if (otherGroup === group) continue; // Skip self

        const ogX1 = otherGroup.pos[0];
        // eslint-disable-next-line no-unused-vars
        // const ogY1 = otherGroup.pos[1]; // Removed as unused
        const ogX2 = otherGroup.pos[0] + otherGroup.size[0];
        const ogY2 = otherGroup.pos[1] + otherGroup.size[1]; // Bottom edge of other group

        // 1. Check for horizontal overlap
        const horizontalOverlap = Math.max(groupX1, ogX1) < Math.min(groupX2, ogX2);

        // 2. Check if otherGroup is strictly above and within tolerance
        const verticalDistance = groupY1 - ogY2; // Positive if group is below otherGroup
        const isAboveAndClose = verticalDistance >= -snapSpacing && verticalDistance <= snapTolerance; // Allow small overlap/touching up to tolerance

        if (horizontalOverlap && isAboveAndClose) {
            // 3. Check if this is the closest group found so far
            if (verticalDistance < minVerticalDistance) {
                minVerticalDistance = verticalDistance;
                closestGroupAbove = otherGroup;
            }
        }
    }

    // If a suitable group was found above, snap to it
    let snapped = false;
    if (closestGroupAbove) {
        const targetGroupY = closestGroupAbove.pos[1] + closestGroupAbove.size[1] + snapSpacing;
        const deltaY = targetGroupY - group.pos[1]; // How much the group needs to move vertically

        // Function to check for overlap at a given position
        const checkOverlapAtPosition = (targetX, targetY) => {
            const newGroupBounds = [targetX, targetY, group.size[0], group.size[1]];
            
            for (const otherGroup of canvas.graph._groups) {
                if (otherGroup === group || otherGroup === closestGroupAbove) continue; // Skip self and the group we're snapping to

                // Ensure the other group has bounding calculated
                if (!otherGroup._bounding) {
                    otherGroup.computeBounding();
                }
                
                if (LiteGraph.overlapBounding(newGroupBounds, otherGroup._bounding)) {
                    return otherGroup; // Return the overlapping group
                }
            }
            return null; // No overlap
        };

        // Try left alignment first (align left borders)
        let targetGroupX = closestGroupAbove.pos[0];
        let overlappingGroup = checkOverlapAtPosition(targetGroupX, targetGroupY);
        let alignmentType = "left";

        // If left alignment would cause overlap, try right alignment (align right borders)
        if (overlappingGroup) {
            const rightAlignTargetX = (closestGroupAbove.pos[0] + closestGroupAbove.size[0]) - group.size[0];
            const rightOverlappingGroup = checkOverlapAtPosition(rightAlignTargetX, targetGroupY);
            
            if (!rightOverlappingGroup) {
                // Right alignment works, use it
                targetGroupX = rightAlignTargetX;
                overlappingGroup = null;
                alignmentType = "right";
            }
        }

        // Only proceed with the snap if we found a valid position
        if (!overlappingGroup) {
            const deltaX = targetGroupX - group.pos[0]; // How much the group needs to move horizontally

            // Move the group
            group.pos[0] = targetGroupX;
            group.pos[1] = targetGroupY;

            // Ensure the group has its nodes loaded if necessary for movement
            if (!group._nodes || group._nodes.length === 0) {
                group.recomputeInsideNodes();
            }

            // Move the nodes inside the group by the same amount
            if (group._nodes) {
                for (const node of group._nodes) {
                    node.pos[0] += deltaX; // Move horizontally
                    node.pos[1] += deltaY; // Move vertically
                }
            }
            snapped = true;
            console.log(`Vertical snap successful: ${alignmentType} alignment used`);
        } else {
            console.log("Vertical snap cancelled: both left and right alignments would cause overlap");
        }
    }

    if (snapped) {
        canvas.graph.afterChange();
        canvas.setDirty(true, true);
        return true; // Indicate the event was handled and a snap occurred
    } else {
        canvas.graph.afterChange(); // Ensure graph state is consistent even if no snap
        return false; // Indicate no snap occurred
    }
}

/**
 * Duplicates a group when its title is Shift+Clicked.
 * @param {LGraphGroup} group The group to duplicate.
 * @param {LGraphCanvas} canvas The canvas instance.
 */
export function handleDuplicateGroup(group, canvas) {
    const new_title = group.title;
    const new_color = group.color;
    // Define a default height or consider calculating based on content if needed
    const defaultHeight = 300;
    const new_size = [group.size[0], defaultHeight];
    // Position below the original group with some spacing
    const spacing = GROUP_SPACING; // Increased spacing
    const new_pos = [group.pos[0], group.pos[1] + group.size[1] + spacing];
    const new_group_bounds = [new_pos[0], new_pos[1], new_size[0], new_size[1]];

    let overlapDetected = false;
    for (const existing_group of canvas.graph._groups) {
        if (existing_group === group) continue; // Skip self
        // Ensure the existing group has bounding calculated
        if (!existing_group._bounding) {
             existing_group.computeBounding();
        }
        if (LiteGraph.overlapBounding(new_group_bounds, existing_group._bounding)) {
            overlapDetected = true;
            console.warn("New group would overlap with existing group:", existing_group.title);
            break;
        }
    }

    if (!overlapDetected) {
       canvas.graph.beforeChange();
       const new_group = new LiteGraph.LGraphGroup();
       new_group.title = new_title;
       new_group.color = new_color;
       new_group.size = new_size;
       new_group.pos = new_pos;
       canvas.graph.add(new_group);
       canvas.graph.afterChange();
       canvas.setDirty(true, true);

        // Reset canvas state to avoid unintended dragging
        canvas.node_dragged = null;
        canvas.dragging_canvas = false;
        canvas.selected_group = null;
        canvas.last_mouse_dragging = false;
        return true; // Indicate the event was handled
    } else {
        console.log("Skipping group duplication due to overlap.");
        return true; // Event handled (by preventing default), even if no duplication
    }
} 