import logging
import os
import re
import urllib.parse

logger = logging.getLogger(__name__)

FERRAMENTAS = [
    {
        "type": "function",
        "function": {
            "name": "anotar_fato",
            "description": (
                "Memoriza um fato importante sobre o usuario ou o mundo para nunca esquecer. "
                "Use isso quando o usuario pedir para 'lembrar', 'anotar', 'decorar' ou "
                "quando ele mencionar algo pessoal relevante."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sujeito": {
                        "type": "string",
                        "description": "O sujeito do fato.",
                    },
                    "relacao": {
                        "type": "string",
                        "description": "A acao ou relacao.",
                    },
                    "objeto": {
                        "type": "string",
                        "description": "O valor ou objeto do fato.",
                    },
                },
                "required": ["sujeito", "relacao", "objeto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pesquisa_web",
            "description": "Pesquisa informacoes em tempo real na internet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "A busca em portugues ou ingles."}
                },
                "required": ["query"],
            },
        },
    },
]


class ToolManager:
    def __init__(self, memory_manager=None):
        self.memory_manager = memory_manager
        self._tavily = None
        self._setup_tavily()

    def _setup_tavily(self):
        try:
            from tavily import TavilyClient

            api_key = os.getenv("TAVILY_API_KEY")
            if api_key:
                self._tavily = TavilyClient(api_key=api_key)
                logger.info("[TOOL MANAGER] Tavily configurado.")
        except Exception:
            pass

    @property
    def ferramentas(self) -> list:
        return FERRAMENTAS

    def executar_tool(self, nome_tool: str, args: dict) -> tuple:
        if nome_tool == "anotar_fato":
            return self._despachar_anotacao(args)

        if nome_tool == "analisar_youtube":
            return self._despachar_youtube(args)

        if nome_tool == "pesquisa_web":
            return self._despachar_web(args)

        logger.warning("[TOOL MANAGER] Tool desconhecida: %s", nome_tool)
        return ("Menu_Tool nao reconhecida pelo sistema.", "Nao reconheci essa acao.")

    def _despachar_web(self, args: dict) -> tuple:
        query = args.get("query", "")
        if not query or not self._tavily:
            return ("Tavily desabilitado ou query vazia.", "Nao consegui pesquisar isso agora, mestre.")

        try:
            logger.info("[TOOL WEB] Pesquisando: %s", query)
            search_result = self._tavily.search(query, max_results=3)
            results = search_result.get("results", [])

            if not results:
                return (f"Nenhum resultado para '{query}'", "Nao encontrei nada sobre isso na internet.")

            lines = [f"Resultados para '{query}':"]
            for result in results:
                title = result.get("title")
                content = (result.get("content") or "")[:300]
                url = result.get("url")
                lines.append(f"- {title}: {content}... ({url})")

            contexto = "\n".join(lines)
            return (contexto, f"Dei uma olhada na internet sobre {query} e descobri algumas coisas.")
        except Exception as exc:
            logger.error("[TOOL WEB] Erro: %s", exc)
            return (f"Erro na pesquisa web: {exc}", "Tive um probleminha tecnico ao pesquisar na internet.")

    def _despachar_anotacao(self, args: dict) -> tuple:
        sujeito = args.get("sujeito", "")
        relacao = args.get("relacao", "")
        objeto = args.get("objeto", "")

        if not (sujeito and relacao and objeto):
            return ("Dados incompletos para anotar o fato.", "Ops, nao entendi o que voce quer que eu anote.")

        if not self.memory_manager:
            logger.warning("[TOOL] MemoryManager nao configurado no ToolManager.")
            return ("MemoryManager indisponivel.", "Nao consigo guardar isso na memoria permanente agora.")

        try:
            self.memory_manager.add_fact(sujeito, relacao, objeto)
            msg_cons = f"Fato gravado: {sujeito} --[{relacao}]--> {objeto}"
            logger.info("[TOOL] %s", msg_cons)
            return (msg_cons, f"Entendido. Anotei aqui que {sujeito} {relacao} {objeto}.")
        except Exception as exc:
            logger.error("[TOOL] Erro ao gravar fato: %s", exc)
            return (f"Erro tecnico ao salvar memoria: {exc}", "Tive um problema ao tentar guardar essa informacao.")

    def _extrair_video_id(self, url: str) -> str | None:
        parsed = urllib.parse.urlparse(url)
        video_id = None

        if "youtube.com" in parsed.netloc:
            video_id = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
            if not video_id:
                path_match = re.match(r"/(?:shorts|live|embed)/([a-zA-Z0-9_-]+)", parsed.path)
                if path_match:
                    video_id = path_match.group(1)
        elif "youtu.be" in parsed.netloc:
            video_id = parsed.path.lstrip("/")

        return video_id

    def _despachar_youtube(self, args: dict) -> tuple:
        url = args.get("url", "")
        if not url:
            return ("URL vazio.", "Voce me passou um link do YouTube vazio.")

        try:
            video_id = self._extrair_video_id(url)
            if not video_id:
                return ("ID de video nao encontrado no link.", "Nao encontrei qual e o video nesse link.")
        except Exception as exc:
            logger.error("[TOOL YOUTUBE] Erro ao parsear URL: %s", exc)
            return (f"Erro parse: {exc}", "O formato do link esta meio estranho.")

        logger.info("[TOOL YOUTUBE] Puxando legendas para ID: %s", video_id)

        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            transcript = YouTubeTranscriptApi().fetch(
                video_id,
                languages=["pt", "en", "es"],
                preserve_formatting=False,
            )

            textos = [f"[{item.start:.1f}s] {item.text}" for item in transcript]
            texto_completo = "\n".join(textos)
            bloco_retorno = (
                f"--- TRANSCRICAO YOUTUBE ({video_id}) ---\n"
                f"{texto_completo}\n"
                f"--- FIM DA TRANSCRICAO ---\n"
            )

            if len(bloco_retorno) > 200000:
                bloco_retorno = bloco_retorno[:200000] + "\n\n...[TRUNCADO: VIDEO MUITO LONGO]..."

            return (bloco_retorno, "Prontinho, ja li a transcricao do video inteiro.")
        except ImportError:
            return (
                "Biblioteca youtube_transcript_api nao instalada.",
                "Preciso que instalem a biblioteca para baixar legendas do YouTube.",
            )
        except Exception as exc:
            logger.error("[TOOL YOUTUBE] Erro ao baixar legenda: %s", exc)
            return (
                f"Erro Youtube API: {exc}",
                "Nao consegui ler as legendas desse video. Talvez ele nao tenha legenda publica, esteja privado ou bloqueado.",
            )
