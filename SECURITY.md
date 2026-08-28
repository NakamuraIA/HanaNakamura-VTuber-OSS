# Política de Segurança

## Versões com suporte

Enquanto o projeto estiver em desenvolvimento, somente a versão mais recente
da branch `main` recebe correções. Versões antigas e forks podem não receber a
mesma correção.

## Avisos importantes

A Hana pode executar comandos, ler e escrever arquivos e controlar recursos do
computador quando as ferramentas locais estão habilitadas. Além disso, a API
local não possui senha.

- mantenha `HANA_BACKEND_HOST=127.0.0.1`;
- não exponha as portas do backend na rede;
- nunca publique `.env`, chaves, bancos, registros ou dados de `runtime/`;
- revise comandos e ações com efeito no computador;
- use apenas providers e servidores MCP em que você confia.

## Como relatar uma vulnerabilidade

Não publique detalhes sensíveis em uma issue (registro de problema).

Quando o repositório público oferecer **Private vulnerability reporting**
(relato privado de vulnerabilidade), use o botão **Report a vulnerability** na
aba **Security** do GitHub. Se ele ainda não estiver disponível, contate a
manutenção pelo perfil GitHub `NakamuraIA` e peça um canal privado sem incluir
o detalhe da falha na mensagem pública.

Inclua, quando possível:

- versão ou commit afetado;
- forma mínima de reproduzir;
- impacto observado;
- sugestão de correção, se houver.

A manutenção avaliará o relato antes de divulgar detalhes ou uma correção.

