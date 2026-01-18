<template>
  <div
    class="bbox-editor"
    ref="container"
    tabindex="0"
    @pointerdown="onPointerDown"
  >
    <img
      v-if="src"
      ref="img"
      :src="src"
      class="bbox-image"
      draggable="false"
    />

    <div v-if="hasBox" class="bbox-overlay">
      <!-- dim outside crop -->
      <div
        v-for="(style, position) in dimStyles"
        :key="position"
        :class="['dim', `dim-${position}`]"
        :style="style"
      ></div>

      <!-- crop box -->
      <div class="bbox-rect" :style="rectStyle" @pointerdown.stop="onRectPointerDown">
        <div
          v-for="corner in ['tl', 'tr', 'bl', 'br']"
          :key="corner"
          :class="['handle', corner]"
          @pointerdown.stop="onHandlePointerDown(corner, $event)"
        ></div>
      </div>
    </div>

    <div class="toolbar">
      <v-btn size="small" variant="tonal" color="primary" @click.stop="resetBox" prepend-icon="mdi-refresh">
        Reset
      </v-btn>
    </div>

    <div class="hint" v-if="!hasBox">
      Drag on the image to set the cover crop.
    </div>
  </div>
</template>

<script>
// Constants
const DEFAULT_ASPECT = 3 / 4; // kept for backwards-compat; no constraints enforced
const MIN_BOX_SIZE = 0.01;
const EPSILON = 1e-6; // for rounding/clamping precision
const ROUND_PRECISION = 1e6;

// Corner anchor lookup table: maps corner to its opposite anchor corner
const CORNER_ANCHORS = {
  tl: (box) => ({ x: box.x + box.w, y: box.y + box.h }), // bottom-right
  tr: (box) => ({ x: box.x, y: box.y + box.h }), // bottom-left
  bl: (box) => ({ x: box.x + box.w, y: box.y }), // top-right
  br: (box) => ({ x: box.x, y: box.y }), // top-left
};

// Corner clamp bounds lookup: maps corner to min/max bounds for x and y
const CORNER_CLAMP_BOUNDS = {
  tl: (anchor, minSize) => ({ xMin: 0, xMax: anchor.x - minSize, yMin: 0, yMax: anchor.y - minSize }),
  tr: (anchor, minSize) => ({ xMin: anchor.x + minSize, xMax: 1, yMin: 0, yMax: anchor.y - minSize }),
  bl: (anchor, minSize) => ({ xMin: 0, xMax: anchor.x - minSize, yMin: anchor.y + minSize, yMax: 1 }),
  br: (anchor, minSize) => ({ xMin: anchor.x + minSize, xMax: 1, yMin: anchor.y + minSize, yMax: 1 }),
};

function clamp(v, min, max) {
  return Math.min(max, Math.max(min, v));
}

function round6(v) {
  return Math.round(v * ROUND_PRECISION) / ROUND_PRECISION;
}

function normalizeBox(box) {
  if (!box) return null;
  let x = round6(box.x);
  let y = round6(box.y);
  let w = round6(box.w);
  let h = round6(box.h);

  // Hard clamp after rounding so we never violate backend validation.
  // Note: backend requires x,y in [0,1) and w,h > 0.
  x = clamp(x, 0, 1 - EPSILON);
  y = clamp(y, 0, 1 - EPSILON);
  w = clamp(w, 0, 1);
  h = clamp(h, 0, 1);

  if (x + w > 1) w = round6(Math.max(0, 1 - x));
  if (y + h > 1) h = round6(Math.max(0, 1 - y));

  if (w <= 0 || h <= 0) return null;

  return { x, y, w, h };
}

export default {
  name: 'CoverBBoxEditor',
  props: {
    modelValue: {
      type: Object,
      default: null,
    },
    src: {
      type: String,
      default: '',
    },
    aspect: {
      type: Number,
      default: DEFAULT_ASPECT,
      // Note: kept for backwards-compat; no constraints enforced
    },
  },
  emits: ['update:modelValue'],
  data() {
    return {
      localBox: this.modelValue ? { ...this.modelValue } : null,
      drag: null, // {mode, start, boxAtStart, corner, offset}
      lastCommittedBox: this.modelValue ? { ...this.modelValue } : null,
    };
  },
  computed: {
    hasBox() {
      return !!(this.localBox && this.localBox.w > 0 && this.localBox.h > 0);
    },
    rectStyle() {
      if (!this.hasBox) return {};
      const b = this.localBox;
      return {
        left: (b.x * 100) + '%',
        top: (b.y * 100) + '%',
        width: (b.w * 100) + '%',
        height: (b.h * 100) + '%',
      };
    },
    dimStyles() {
      if (!this.hasBox) return {};
      const b = this.localBox;
      return {
        top: { left: '0%', top: '0%', width: '100%', height: (b.y * 100) + '%' },
        left: { left: '0%', top: (b.y * 100) + '%', width: (b.x * 100) + '%', height: (b.h * 100) + '%' },
        right: { left: ((b.x + b.w) * 100) + '%', top: (b.y * 100) + '%', width: ((1 - (b.x + b.w)) * 100) + '%', height: (b.h * 100) + '%' },
        bottom: { left: '0%', top: ((b.y + b.h) * 100) + '%', width: '100%', height: ((1 - (b.y + b.h)) * 100) + '%' },
      };
    },
  },
  watch: {
    modelValue: {
      deep: true,
      handler(v) {
        this.localBox = this.copyBox(v);
        this.lastCommittedBox = this.copyBox(v);
      },
    },
  },
  methods: {
    // Helper methods for box operations
    copyBox(box) {
      return box ? { ...box } : null;
    },

    isPointInBox(point, box) {
      return point.x >= box.x && point.x <= (box.x + box.w) && point.y >= box.y && point.y <= (box.y + box.h);
    },

    createBoxFromPoints(p1, p2) {
      const x = Math.min(p1.x, p2.x);
      const y = Math.min(p1.y, p2.y);
      const w = Math.abs(p2.x - p1.x);
      const h = Math.abs(p2.y - p1.y);
      return { x, y, w, h };
    },

    clampBoxToBounds(box, minSize) {
      let { x, y, w, h } = box;
      
      // Ensure minimum size
      w = Math.max(w, minSize);
      h = Math.max(h, minSize);

      // Clamp position to bounds
      x = clamp(x, 0, 1 - minSize);
      y = clamp(y, 0, 1 - minSize);
      
      // Shrink if box extends beyond bounds
      if (x + w > 1) w = Math.max(minSize, 1 - x);
      if (y + h > 1) h = Math.max(minSize, 1 - y);

      return { x, y, w, h };
    },

    getCornerAnchor(corner, box) {
      const anchorFn = CORNER_ANCHORS[corner];
      return anchorFn ? anchorFn(box) : null;
    },

    clampCornerPoint(point, corner, anchor) {
      const bounds = CORNER_CLAMP_BOUNDS[corner](anchor, MIN_BOX_SIZE);
      return {
        x: clamp(point.x, bounds.xMin, bounds.xMax),
        y: clamp(point.y, bounds.yMin, bounds.yMax),
      };
    },

    emitBox(box) {
      const normalized = normalizeBox(box);
      this.localBox = normalized;
      this.$emit('update:modelValue', normalized);
      this.lastCommittedBox = this.copyBox(normalized);
    },

    getRelPoint(evt) {
      const img = this.$refs.img;
      if (!img) return null;
      const rect = img.getBoundingClientRect();
      const x = clamp((evt.clientX - rect.left) / rect.width, 0, 1);
      const y = clamp((evt.clientY - rect.top) / rect.height, 0, 1);
      return { x, y };
    },

    resetBox() {
      // Reset == full image (no crop)
      this.emitBox({ x: 0, y: 0, w: 1, h: 1 });
    },

    beginDrag(drag) {
      this.drag = drag;
      window.addEventListener('pointermove', this.onPointerMove, { passive: false });
      window.addEventListener('pointerup', this.onPointerUp, { passive: false });
    },

    endDrag(commit = true) {
      window.removeEventListener('pointermove', this.onPointerMove);
      window.removeEventListener('pointerup', this.onPointerUp);
      if (!commit) {
        // restore last committed box
        this.localBox = this.copyBox(this.lastCommittedBox);
        this.$emit('update:modelValue', this.copyBox(this.localBox));
      } else {
        // commit updates were already emitted during drag
        this.lastCommittedBox = this.copyBox(this.localBox);
      }
      this.drag = null;
    },

    startMoveDrag(point) {
      const b = this.localBox;
      const offset = { x: point.x - b.x, y: point.y - b.y };
      this.beginDrag({ mode: 'move', start: point, boxAtStart: this.copyBox(b), offset });
    },

    onPointerDown(e) {
      if (e.button != null && e.button !== 0) return;
      if (this.drag) return;

      const p = this.getRelPoint(e);
      if (!p) return;

      // If click inside box, move; otherwise draw new
      if (this.hasBox && this.isPointInBox(p, this.localBox)) {
        this.startMoveDrag(p);
        return;
      }

      // Start drawing a new box
      this.beginDrag({ mode: 'draw', start: p, boxAtStart: null });
    },

    onRectPointerDown(e) {
      // Move when dragging inside the rect.
      if (e.button != null && e.button !== 0) return;
      const p = this.getRelPoint(e);
      if (!p || !this.hasBox) return;
      this.startMoveDrag(p);
    },

    onHandlePointerDown(corner, e) {
      if (e.button != null && e.button !== 0) return;
      if (!this.hasBox) return;
      const p = this.getRelPoint(e);
      if (!p) return;
      this.beginDrag({ mode: 'resize', start: p, boxAtStart: this.copyBox(this.localBox), corner });
    },

    onPointerMove(e) {
      if (!this.drag) return;
      e.preventDefault();

      const p = this.getRelPoint(e);
      if (!p) return;

      if (this.drag.mode === 'move') {
        const b0 = this.drag.boxAtStart;
        const nx = clamp(p.x - this.drag.offset.x, 0, 1 - b0.w);
        const ny = clamp(p.y - this.drag.offset.y, 0, 1 - b0.h);
        this.emitBox({ x: nx, y: ny, w: b0.w, h: b0.h });
        return;
      }

      if (this.drag.mode === 'draw') {
        const box = this.createBoxFromPoints(this.drag.start, p);
        const clampedBox = this.clampBoxToBounds(box, MIN_BOX_SIZE);
        this.emitBox(clampedBox);
        return;
      }

      if (this.drag.mode === 'resize') {
        const b0 = this.drag.boxAtStart;
        const corner = this.drag.corner;
        const anchor = this.getCornerAnchor(corner, b0);
        
        if (!anchor) return;

        // Clamp pointer into valid quadrant so the box doesn't invert, and to image bounds.
        const clampedPoint = this.clampCornerPoint(p, corner, anchor);

        // Create box from anchor and clamped point
        const x = Math.min(anchor.x, clampedPoint.x);
        const y = Math.min(anchor.y, clampedPoint.y);
        const w = Math.abs(clampedPoint.x - anchor.x);
        const h = Math.abs(clampedPoint.y - anchor.y);

        const box = { x, y, w, h };
        const clampedBox = this.clampBoxToBounds(box, MIN_BOX_SIZE);
        this.emitBox(clampedBox);
      }
    },

    onPointerUp(e) {
      if (!this.drag) return;
      this.endDrag(true);
    },
  },
};
</script>

<style scoped>
.bbox-editor {
  position: relative;
  width: 100%;
  user-select: none;
  touch-action: none;
}

.bbox-image {
  display: block;
  width: 100%;
  height: auto;
}

.bbox-overlay {
  position: absolute;
  inset: 0;
}

.dim {
  position: absolute;
  background: rgba(0, 0, 0, 0.45);
  pointer-events: none;
}

.bbox-rect {
  position: absolute;
  border: 2px solid rgb(var(--v-theme-primary));
  box-shadow: 0 0 0 1px rgba(0,0,0,0.35);
  cursor: move;
}

.handle {
  position: absolute;
  width: 14px;
  height: 14px;
  background: rgb(var(--v-theme-primary));
  border-radius: 3px;
  box-shadow: 0 0 0 2px rgba(0,0,0,0.25);
}

.handle.tl { left: -7px; top: -7px; cursor: nwse-resize; }
.handle.tr { right: -7px; top: -7px; cursor: nesw-resize; }
.handle.bl { left: -7px; bottom: -7px; cursor: nesw-resize; }
.handle.br { right: -7px; bottom: -7px; cursor: nwse-resize; }

.toolbar {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  gap: 8px;
  z-index: 5;
}

.hint {
  position: absolute;
  left: 10px;
  bottom: 10px;
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.5);
  color: rgba(255,255,255,0.9);
  font-size: 12px;
  z-index: 5;
}
</style>
