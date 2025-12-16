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
      @load="onImageLoad"
    />

    <div v-if="hasBox" class="bbox-overlay">
      <!-- dim outside crop -->
      <div class="dim dim-top" :style="dimTopStyle"></div>
      <div class="dim dim-left" :style="dimLeftStyle"></div>
      <div class="dim dim-right" :style="dimRightStyle"></div>
      <div class="dim dim-bottom" :style="dimBottomStyle"></div>

      <!-- crop box -->
      <div class="bbox-rect" :style="rectStyle" @pointerdown.stop="onRectPointerDown">
        <div class="handle tl" @pointerdown.stop="onHandlePointerDown('tl', $event)"></div>
        <div class="handle tr" @pointerdown.stop="onHandlePointerDown('tr', $event)"></div>
        <div class="handle bl" @pointerdown.stop="onHandlePointerDown('bl', $event)"></div>
        <div class="handle br" @pointerdown.stop="onHandlePointerDown('br', $event)"></div>
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
const DEFAULT_ASPECT = 3 / 4; // kept for backwards-compat; no constraints enforced

function clamp(v, min, max) {
  return Math.min(max, Math.max(min, v));
}

function round6(v) {
  return Math.round(v * 1e6) / 1e6;
}

function normalizeBox(box) {
  if (!box) return null;
  let x = round6(box.x);
  let y = round6(box.y);
  let w = round6(box.w);
  let h = round6(box.h);

  // Hard clamp after rounding so we never violate backend validation.
  // Note: backend requires x,y in [0,1) and w,h > 0.
  x = clamp(x, 0, 1 - 1e-6);
  y = clamp(y, 0, 1 - 1e-6);
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
    dimTopStyle() {
      if (!this.hasBox) return {};
      return { left: '0%', top: '0%', width: '100%', height: (this.localBox.y * 100) + '%' };
    },
    dimLeftStyle() {
      if (!this.hasBox) return {};
      const b = this.localBox;
      return { left: '0%', top: (b.y * 100) + '%', width: (b.x * 100) + '%', height: (b.h * 100) + '%' };
    },
    dimRightStyle() {
      if (!this.hasBox) return {};
      const b = this.localBox;
      return { left: ((b.x + b.w) * 100) + '%', top: (b.y * 100) + '%', width: ((1 - (b.x + b.w)) * 100) + '%', height: (b.h * 100) + '%' };
    },
    dimBottomStyle() {
      if (!this.hasBox) return {};
      const b = this.localBox;
      return { left: '0%', top: ((b.y + b.h) * 100) + '%', width: '100%', height: ((1 - (b.y + b.h)) * 100) + '%' };
    },
  },
  watch: {
    modelValue: {
      deep: true,
      handler(v) {
        this.localBox = v ? { ...v } : null;
        this.lastCommittedBox = v ? { ...v } : null;
      },
    },
  },
  methods: {
    onImageLoad() {
      // no-op; placeholder hook
    },

    emitBox(box) {
      const normalized = normalizeBox(box);
      this.localBox = normalized;
      this.$emit('update:modelValue', normalized);
      this.lastCommittedBox = normalized ? { ...normalized } : null;
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
        this.localBox = this.lastCommittedBox ? { ...this.lastCommittedBox } : null;
        this.$emit('update:modelValue', this.localBox ? { ...this.localBox } : null);
      } else {
        // commit updates were already emitted during drag
        this.lastCommittedBox = this.localBox ? { ...this.localBox } : null;
      }
      this.drag = null;
    },

    onPointerDown(e) {
      if (e.button != null && e.button !== 0) return;
      if (this.drag) return;

      const p = this.getRelPoint(e);
      if (!p) return;

      // If click inside box, move; otherwise draw new
      if (this.hasBox) {
        const b = this.localBox;
        const inside = p.x >= b.x && p.x <= (b.x + b.w) && p.y >= b.y && p.y <= (b.y + b.h);
        if (inside) {
          const offset = { x: p.x - b.x, y: p.y - b.y };
          this.beginDrag({ mode: 'move', start: p, boxAtStart: { ...b }, offset });
          return;
        }
      }

      // Start drawing a new box
      this.beginDrag({ mode: 'draw', start: p, boxAtStart: null });
    },

    onRectPointerDown(e) {
      // Move when dragging inside the rect.
      if (e.button != null && e.button !== 0) return;
      const p = this.getRelPoint(e);
      if (!p || !this.hasBox) return;
      const b = this.localBox;
      const offset = { x: p.x - b.x, y: p.y - b.y };
      this.beginDrag({ mode: 'move', start: p, boxAtStart: { ...b }, offset });
    },

    onHandlePointerDown(corner, e) {
      if (e.button != null && e.button !== 0) return;
      if (!this.hasBox) return;
      const p = this.getRelPoint(e);
      if (!p) return;
      this.beginDrag({ mode: 'resize', start: p, boxAtStart: { ...this.localBox }, corner });
    },

    onPointerMove(e) {
      if (!this.drag) return;
      e.preventDefault();

      const p = this.getRelPoint(e);
      if (!p) return;

      const minSize = 0.01;

      if (this.drag.mode === 'move') {
        const b0 = this.drag.boxAtStart;
        const nx = clamp(p.x - this.drag.offset.x, 0, 1 - b0.w);
        const ny = clamp(p.y - this.drag.offset.y, 0, 1 - b0.h);
        this.emitBox({ x: nx, y: ny, w: b0.w, h: b0.h });
        return;
      }

      if (this.drag.mode === 'draw') {
        const s = this.drag.start;
        let x1 = s.x;
        let y1 = s.y;
        let x2 = p.x;
        let y2 = p.y;

        let x = Math.min(x1, x2);
        let y = Math.min(y1, y2);
        let w = Math.abs(x2 - x1);
        let h = Math.abs(y2 - y1);

        w = Math.max(w, minSize);
        h = Math.max(h, minSize);

        // Clamp to bounds (keep top-left, shrink if needed)
        x = clamp(x, 0, 1 - minSize);
        y = clamp(y, 0, 1 - minSize);
        if (x + w > 1) w = Math.max(minSize, 1 - x);
        if (y + h > 1) h = Math.max(minSize, 1 - y);

        this.emitBox({ x, y, w, h });
        return;
      }

      if (this.drag.mode === 'resize') {
        const b0 = this.drag.boxAtStart;
        const corner = this.drag.corner;

        // Anchor is the opposite corner (fixed). Pointer moves the selected corner.
        let ax, ay;
        if (corner === 'tl') {
          ax = b0.x + b0.w; ay = b0.y + b0.h; // bottom-right
        } else if (corner === 'tr') {
          ax = b0.x; ay = b0.y + b0.h; // bottom-left
        } else if (corner === 'bl') {
          ax = b0.x + b0.w; ay = b0.y; // top-right
        } else {
          ax = b0.x; ay = b0.y; // top-left
        }

        // Clamp pointer into valid quadrant so the box doesn't invert, and to image bounds.
        let px = p.x;
        let py = p.y;

        if (corner === 'tl') {
          px = clamp(px, 0, ax - minSize);
          py = clamp(py, 0, ay - minSize);
        } else if (corner === 'tr') {
          px = clamp(px, ax + minSize, 1);
          py = clamp(py, 0, ay - minSize);
        } else if (corner === 'bl') {
          px = clamp(px, 0, ax - minSize);
          py = clamp(py, ay + minSize, 1);
        } else if (corner === 'br') {
          px = clamp(px, ax + minSize, 1);
          py = clamp(py, ay + minSize, 1);
        }

        let x = Math.min(ax, px);
        let y = Math.min(ay, py);
        let w = Math.abs(px - ax);
        let h = Math.abs(py - ay);

        w = Math.max(w, minSize);
        h = Math.max(h, minSize);

        // Clamp to bounds by shrinking if needed.
        x = clamp(x, 0, 1 - minSize);
        y = clamp(y, 0, 1 - minSize);
        if (x + w > 1) w = Math.max(minSize, 1 - x);
        if (y + h > 1) h = Math.max(minSize, 1 - y);

        this.emitBox({ x, y, w, h });
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
