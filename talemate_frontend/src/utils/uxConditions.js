import { getProperty } from 'dot-prop';

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

// Agent-side resolution: the condition attribute names an action config value.
// A non-dict agent `client` satisfies the condition — the dynamic-children
// pattern installs object-shaped clients for some agents, and their actions
// must stay visible.
export function agentActionConditionMet(condition, actions, agentClient) {
  if (condition == null) return true;
  if (typeof agentClient !== 'object') return true;
  return conditionMet(condition, getProperty(actions, condition.attribute + '.value'));
}
