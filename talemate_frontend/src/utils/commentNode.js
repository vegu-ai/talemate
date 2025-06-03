import { LiteGraph } from 'litegraph.js';

// Define the Comment node class
export function CommentNode() {
    this.properties = { text: "Comment" };
    this.color = "rgba(0,0,0,0.1)"; // Transparent border
    this.bgcolor = "rgba(0,0,0,0.05)"; // Very transparent background
    this.size = [200, 100];
    this.resizable = true;
    this.removable = true;
    this.collapsable = false; // Comments cannot be collapsed
}

CommentNode.title = "Comment";
CommentNode.desc = "Add a text comment";

// Remove the title bar completely
CommentNode.title_mode = LiteGraph.NO_TITLE;

// Custom function to measure text width in a canvas
CommentNode.prototype.getTextWidth = function(text, font) {
  // Create a temporary canvas
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  context.font = font || "italic 14px Arial";
  return context.measureText(text).width;
};

// Custom function to wrap text based on width
CommentNode.prototype.wrapText = function(text, maxWidth) {
  if (!text) return [];
  
  const words = text.split(' ');
  const lines = [];
  let currentLine = words[0];

  const font = "14px Arial";
  
  for (let i = 1; i < words.length; i++) {
    const word = words[i];
    const width = this.getTextWidth(currentLine + ' ' + word, font);
    
    if (width < maxWidth - 20) { // 20px for padding
      currentLine += ' ' + word;
    } else {
      lines.push(currentLine);
      currentLine = word;
    }
  }
  
  lines.push(currentLine);
  return lines;
};

// Draw the comment background
CommentNode.prototype.onDrawBackground = function(ctx) {
  ctx.fillStyle = this.bgcolor;
  ctx.strokeStyle = this.color;
  ctx.beginPath();
  ctx.roundRect(0, 0, this.size[0], this.size[1], [8]);
  ctx.fill();
  ctx.stroke();
};

// Draw the comment text
CommentNode.prototype.onDrawForeground = function(ctx) {
  if (!this.properties.text) return;
  
  ctx.font = "italic 14px Arial";
  ctx.fillStyle = "#AAA";
  ctx.textAlign = "left";
  
  // Get wrapped lines based on current node width
  const maxTextWidth = this.size[0] - 20; // Account for padding
  
  // Split text by newlines first
  const paragraphs = this.properties.text.split("\n");
  let allLines = [];
  
  // Wrap each paragraph and preserve empty lines
  for (let i = 0; i < paragraphs.length; i++) {
    // If paragraph is empty string, it's a blank line
    if (paragraphs[i] === "") {
      allLines.push("");
    } else {
      const wrappedLines = this.wrapText(paragraphs[i], maxTextWidth);
      allLines = allLines.concat(wrappedLines);
    }
  }
  
  // Draw each line
  const lineHeight = 20;
  for (let i = 0; i < allLines.length; i++) {
    ctx.fillText(allLines[i], 10, 20 + i * lineHeight);
  }
  
  const minHeight = 15;

  // Auto-adjust height only
  const requiredHeight = Math.max(minHeight, allLines.length * lineHeight + minHeight);
  if (this.size[1] !== requiredHeight) {
    this.size[1] = requiredHeight;
  }
};

// Handle node resizing
CommentNode.prototype.onResize = function() {
  // Let LiteGraph handle the redraw
  return true;
};

// Handle double-click to edit the comment text
CommentNode.prototype.onDblClick = function(e, pos, graphcanvas) {
  
  graphcanvas.prompt(
    "Comment text",
    this.properties.text || "",
    (text) => {
      this.properties.text = text;
      graphcanvas.setDirty(true);
    },
    e,
    true,
  )
};

// Comment nodes have no inputs or outputs
CommentNode.prototype.onGetInputs = function() { return []; };
CommentNode.prototype.onGetOutputs = function() { return []; };

// overwrite contextmenu for node
CommentNode.prototype.getMenuOptions = function() {
    return [
    ]
};
