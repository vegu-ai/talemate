// Must match str() repr of BackendStatusType in src/talemate/agents/visual/schema.py
export const BACKEND_STATUS = Object.freeze({
  OK: 'BackendStatusType.OK',
  WARNING: 'BackendStatusType.WARNING',
  ERROR: 'BackendStatusType.ERROR',
  DISCONNECTED: 'BackendStatusType.DISCONNECTED',
});
