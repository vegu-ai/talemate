// Which agents an "assign this client to all agents" action targets.
//
// Only agents that generate with an LLM client are assignable — the save path
// persists `client: null` for every other agent regardless of what the UI put
// there, so assigning to them is a no-op that only looks like it worked.
export function agentsRequiringClient(agents) {
    return (agents || []).filter((agent) => agent?.data?.requires_llm_client);
}
