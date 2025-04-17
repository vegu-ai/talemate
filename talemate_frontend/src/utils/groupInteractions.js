import { LiteGraph } from 'litegraph.js';

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
        minX = Math.min(minX, node.pos[0]);
        minY = Math.min(minY, node.pos[1]);
        maxX = Math.max(maxX, node.pos[0] + node.size[0]);
        maxY = Math.max(maxY, node.pos[1] + node.size[1]);
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
    const spacing = 3; // Increased spacing
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