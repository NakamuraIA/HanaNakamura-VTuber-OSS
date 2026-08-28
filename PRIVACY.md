# Privacidade

## Resumo

A Hana roda no computador da pessoa usuária e não depende de uma conta central
mantida pelo projeto. O projeto não recebe automaticamente seu banco, suas
conversas ou suas chaves.

A Hana, porém, **não é totalmente offline**. Quando você escolhe um serviço
externo, os dados necessários para aquela função são enviados ao serviço.

## Dados guardados localmente

A instalação pode guardar no computador:

- conversas, memórias, regras e configurações no banco SQLite em `runtime/`;
- mídia gerada, arquivos temporários e registros de execução;
- preferências e parte do histórico no armazenamento local do navegador ou do
  WebView do aplicativo;
- chaves de API e identificadores no arquivo `.env`.

Não envie `runtime/`, `.env`, bancos ou registros de execução em uma issue
(registro de problema) pública.

## Quando dados são enviados para terceiros

Isso depende dos recursos ativados:

- **LLM (modelo de linguagem):** mensagem, contexto, memórias relevantes,
  resultados de ferramentas e anexos podem ser enviados ao provider escolhido;
- **STT (transcrição de fala):** o áudio do microfone é enviado ao serviço de
  transcrição selecionado;
- **TTS (síntese de voz):** o texto a ser falado é enviado ao Edge/Microsoft,
  ElevenLabs ou Fish Audio, conforme a configuração;
- **visão e imagem:** capturas de tela, imagens anexadas, referências e prompts
  podem ser enviados ao provider multimodal ou de imagem;
- **Discord:** mensagens, anexos e identificadores passam pelo Discord e podem
  seguir para o provider de IA escolhido;
- **busca e MCP (Protocolo de Contexto de Modelo):** consultas e argumentos são
  enviados aos servidores externos habilitados, como Tavily;
- **memória semântica:** textos de memória e consultas permanecem locais com
  FastEmbed, ou são enviados ao OpenRouter quando esse modo remoto é escolhido.

Cada serviço externo possui seus próprios termos, retenção e política de
privacidade. Consulte essas políticas antes de enviar conteúdo sensível.

## Controles disponíveis

Você pode reduzir o envio de dados ao:

- não configurar providers que não pretende usar;
- desligar visão, Discord, MCP e ferramentas locais;
- usar embeddings locais;
- revisar anexos e a tela antes de iniciar um turno com visão;
- evitar colocar senhas, tokens ou documentos confidenciais nas conversas.

## Exclusão dos dados locais

Feche a Hana antes de apagar arquivos. Para um reset completo do backend,
remova a pasta `runtime/`. Preferências e históricos do frontend podem exigir
também a limpeza dos dados locais do navegador ou do aplicativo. Mídia salva em
uma pasta personalizada precisa ser removida separadamente.

Excluir dados locais não apaga automaticamente dados que já tenham sido
enviados a um serviço externo. Nesse caso, consulte o próprio provider.

## Segurança

A API local da Hana não possui autenticação. Mantenha o backend ligado apenas
em `127.0.0.1` e nunca exponha sua porta à rede ou à internet.

Para relatar uma vulnerabilidade, siga [SECURITY.md](SECURITY.md).

