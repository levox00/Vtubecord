# Adding AI function tools

The chat route talks only to `ToolRegistry`, the semantic router, and
`run_tool_conversation`. An integration owns its schemas and handlers in one
module, then its registration function is added to `factory.py`. No
model-specific or chat-route changes are needed.

Give each `ToolSpec` broad `intent_hints` such as `("obs", "scene", "start
recording")`. These hints only wake the semantic routing pass; they never pick
or execute a function. The active LLM receives the real schemas and must choose
one registered function or the built-in no-action sentinel. All tools in a
matched category are presented together so it can distinguish related actions.

For an OBS integration, for example, create `obs.py` with a `register_obs_tools`
function and category `obs`. Register narrow actions such as `obs_get_status`
and `obs_set_current_scene` instead of exposing arbitrary WebSocket requests.
Each handler should:

1. check that OBS control is enabled;
2. validate the configured OBS connection and allowed scene;
3. perform the local action;
4. return JSON-safe observed state, not an assumed success message;
5. raise `ToolExecutionError` for safe user-facing failures.

State-changing tools should have strict schemas with
`additionalProperties: false`. Destructive actions such as stopping a stream,
deleting a scene, banning a Discord member, or sending a message as the user
should additionally use an explicit user-confirmation layer before their
handlers are registered.

The provider adapter passes standard OpenAI function definitions to compatible
servers and also supplies a guarded `<tool_call>` fallback for local Qwen,
Gemma, Llama/Hermes, and NVIDIA Nemotron/Minitron chat templates. The executor
rejects names that are not in the registry and validates arguments before a
handler runs.
