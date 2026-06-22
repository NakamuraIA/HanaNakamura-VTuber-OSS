# Tavily MCP Research Policy

Use Tavily through MCP only when the user asks for current web information,
external source verification, recent news, citations, or public web research.

Available tool flow:

- Use `mcp_discover` to inspect the `tavily` server when tool availability is unclear.
- Use `mcp_invoke` with `server_id="tavily"` and an allowlisted Tavily tool for the actual query.
- Prefer `tavily-search` for web search. Do not assume `tavily-extract` is allowed until discovery/allowlist confirms it.

Rules:

- Never write `mcp_discover(...)` or `mcp_invoke(...)` as visible text; use the real tool call.
- Never use Tavily for normal chat, persona talk, TTS, STT, image generation, local files, or PC automation (use the terminal tools for that).
- Never trigger Tavily only because the user mentioned a word. The model decides from the actual request intent.
- If the MCP tool returns `ok=false`, show the real error exactly and do not invent another cause.
- If Tavily is disabled, missing `TAVILY_API_KEY`, or the tool is not allowlisted, explain the returned backend error and what must be enabled.

## Notas da Hana (aprendidas em uso)
- [2026-06-08] usar search_depth advanced pra notícias
