"""Ferramentas que a IA pode chamar durante uma conversa/turno.

Contrato da pasta: um arquivo por domínio de ferramenta.
- file_tools / terminal_tools   : sistema de arquivos e shell local.
- keyboard_tools / mouse_tools  : controle de teclado/mouse (pynput).
- memory_tools / reminder_tools : memória e lembretes.
- discord_tools                 : ações no Discord.
- skill_tools / script_tools    : skills e scripts de data/.
- mcp_provider_tools            : ponte para servidores MCP externos.

Padrão obrigatório: handlers registrados em ToolRegistry devolvem ToolResult
(backend/core/protocol). Adaptadores usados diretamente por providers podem
serializar esse resultado como dict. Ferramenta não decide política de execução;
o registro OpenAI-compatible fica junto do adaptador compartilhado, separado
por domínio, sem pertencer ao OpenRouter.
"""
