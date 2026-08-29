// Evaluates the shared UX field/action visibility condition
// (talemate.ux.schema.Condition) against an already-resolved value.
//
// Callers own the value resolution — agent settings resolve the condition
// attribute against action config values, client settings against the
// client's field values. Loose equality is intentional: values cross the
// websocket boundary and may arrive as string/number/bool variants.
export function conditionMet(condition, resolvedValue) {
  if (condition == null) return true;
  if (Array.isArray(condition.value)) {
    return condition.value.some(v => v == resolvedValue);
  }
  return resolvedValue == condition.value;
}
