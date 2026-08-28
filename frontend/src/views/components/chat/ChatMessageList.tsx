import { memo } from "react";
import {
  ChevronDown, Copy, Volume2, User, Bot, Trash2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { ChatMessage, ThinkingItem } from "../../../models/types";
import { LONG_MESSAGE_LIMIT } from "../../../models/constants";
import { MediaRenderer } from "./MediaRenderer";
import {
  ToolRunsRenderer, MemoryContextRenderer, SearchSourcesRenderer,
  AgentPlanRenderer, ThinkingRenderer, ErrorDetailRenderer,
} from "./ChatRenderers";
import { fileIconFor, isImageAttachment, attachmentType, attachmentData, attachmentLabel } from "./chatUtils";

// Plain LLM chat turns produce only trivial "llm.provider" steps — only surface agent mode for real tools.
function planHasRealSteps(plan?: ChatMessage["agentPlan"]) {
  const steps = plan?.steps || [];
  return steps.some((step) => {
    const tool = String(step.tool || "").toLowerCase();
    return Boolean(tool) && !tool.startsWith("llm.");
  });
}

// Referencia estavel: passada pra toda linha que NAO esta streamando agora, pra
// nao criar um array novo a cada render (quebraria o memo abaixo por igual).
const EMPTY_THINKING: ThinkingItem[] = [];

// Sugestoes da tela inicial: cobrem as capacidades que ficam escondidas
// (ferramentas, memoria, visao, imagem) em vez de so "diga oi".
const STARTER_PROMPTS: { label: string; prompt: string }[] = [
  { label: "🔎 Pesquisar na web", prompt: "Pesquisa na web pra mim: " },
  { label: "🧠 Lembrar de algo", prompt: "Hana, guarda isso na memoria: " },
  { label: "🎨 Gerar uma imagem", prompt: "Gera uma imagem de " },
  { label: "⏰ Criar lembrete", prompt: "Me lembra de " },
];

/** Chips clicaveis mostrados so quando a conversa ainda nao tem nenhuma troca real. */
function StarterPrompts({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-3 py-6">
      <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
        Comece por aqui
      </span>
      <div className="flex flex-wrap justify-center gap-2">
        {STARTER_PROMPTS.map((item) => (
          <button
            key={item.label}
            type="button"
            onClick={() => onPick(item.prompt)}
            className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-[12px] text-[var(--text-secondary)] transition-colors hover:border-[var(--cyan-neon)]/40 hover:text-white"
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}

interface ChatMessageRowProps {
  msg: ChatMessage;
  renderMessageContent: (msg: ChatMessage) => string;
  isExpanded: boolean;
  onToggleExpand: (msgId: string) => void;
  onDeleteMessage: (msgId: string) => void;
  onDeleteMedia: (msgId: string, mediaIndex: number) => void;
  onGenerateSpeech: (msgId: string, content: string) => void;
  onOpenImage: (url: string) => void;
  identity: { name: string; avatar?: string };
  isTyping: boolean;
  liveThinking: ThinkingItem[];
}

/**
 * Uma bolha de mensagem, memoizada. Numa conversa longa, sem isso o React
 * reprocessava o Markdown de TODO o historico a cada tecla digitada na caixa de
 * texto (o "input" mora no componente pai, entao qualquer keystroke re-renderiza
 * a lista inteira) — era a causa do chat travar com muito texto acumulado.
 * So a mensagem com id "streaming-res" recebe isTyping/liveThinking de verdade;
 * as demais recebem valores constantes (false/EMPTY_THINKING), entao o memo as
 * mantem paradas mesmo enquanto a resposta ao vivo continua atualizando.
 */
const ChatMessageRow = memo(function ChatMessageRow({
  msg,
  renderMessageContent,
  isExpanded,
  onToggleExpand,
  onDeleteMessage,
  onDeleteMedia,
  onGenerateSpeech,
  onOpenImage,
  identity,
  isTyping,
  liveThinking,
}: ChatMessageRowProps) {
  return (
    <div className={`flex w-full animate-fade-in ${msg.role === 'user' ? 'justify-end' : (msg.role === 'system' ? 'justify-center' : 'justify-start')}`}>

      {msg.role === 'system' && (
        <div className="bg-[rgba(255,255,255,0.03)] border border-[var(--border-strong)] text-[var(--text-muted)] text-[10px] px-6 py-2 rounded-full font-mono tracking-tighter uppercase backdrop-blur-sm shadow-sm">
          {msg.content}
        </div>
      )}

      {msg.role === 'user' && (
        <div className="flex flex-col items-end gap-2 max-w-[80%]">
          <div className="flex items-center gap-2 mb-1 px-1">
            <span className="text-[10px] font-mono text-[var(--text-muted)]">{msg.timestamp}</span>
            <span className="text-xs font-black text-blue-400 uppercase tracking-widest">Voce</span>
            <div className="w-6 h-6 rounded-full bg-blue-500/20 border border-blue-500/40 flex items-center justify-center">
              <User size={12} className="text-blue-400" />
            </div>
            <button onClick={() => onDeleteMessage(msg.id)} className="p-1 rounded-lg text-[var(--text-muted)] hover:text-red-300 hover:bg-red-500/10 transition-colors" title="Apagar mensagem">
              <Trash2 size={12} />
            </button>
          </div>

          <div className="bg-[rgba(59,130,246,0.1)] border border-blue-500/30 rounded-3xl rounded-tr-none p-5 shadow-[0_10px_30px_rgba(0,0,0,0.3)] backdrop-blur-xl group relative">
            {/* Miniaturas de anexos enviados */}
            {msg.attachments && msg.attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-4">
                {msg.attachments.map((att, i) => (
                  <div key={i} className="w-28 min-h-24 rounded-xl overflow-hidden border border-white/10 shadow-lg group/img bg-black/25">
                    {isImageAttachment(att) && attachmentData(att) ? (
                      <img src={attachmentData(att)} loading="lazy" className="w-full h-20 object-cover transition-transform group-hover/img:scale-110" alt={attachmentLabel(att, i)} />
                    ) : (
                      <div className="w-full h-20 flex items-center justify-center text-[var(--cyan-neon)]">
                        {fileIconFor(attachmentType(att))}
                      </div>
                    )}
                    <div className="px-2 py-1 text-[9px] text-[var(--text-muted)] truncate">{attachmentLabel(att, i)}</div>
                  </div>
                ))}
              </div>
            )}
            <p className="text-[15px] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap font-medium">{renderMessageContent(msg)}</p>
            {msg.content.length > LONG_MESSAGE_LIMIT && (
              <button
                onClick={() => onToggleExpand(msg.id)}
                className="mt-3 text-[10px] font-black uppercase tracking-widest text-blue-300 hover:text-white"
              >
                {isExpanded ? "Ver menos" : "Ver mais"}
              </button>
            )}
          </div>
        </div>
      )}

      {msg.role === 'hana' && (
        <div className="flex flex-col items-start gap-2 w-full max-w-[90%]">
          <div className="flex items-center gap-2 mb-1 px-1">
            <div className="w-8 h-8 rounded-full bg-[var(--purple-dark)] border border-[var(--purple-neon)] flex items-center justify-center shadow-[0_0_10px_var(--purple-dark)] overflow-hidden">
              <img src={identity.avatar} className="w-full h-full object-cover" alt="H" />
            </div>
            <span className="text-xs font-black text-[var(--purple-neon)] uppercase tracking-[0.2em] drop-shadow-[0_0_5px_var(--purple-dark)]">{identity.name}</span>
            <span className="text-[10px] font-mono text-[var(--text-muted)]">{msg.timestamp}</span>
            <button onClick={() => onDeleteMessage(msg.id)} className="p-1 rounded-lg text-[var(--text-muted)] hover:text-red-300 hover:bg-red-500/10 transition-colors" title="Apagar mensagem">
              <Trash2 size={12} />
            </button>
          </div>

          <div className="w-full relative group/hana pl-1">
            {msg.meta && (
              <div className="mb-4 text-[9px] font-bold font-mono text-[var(--text-muted)] flex items-center gap-3">
                <span className="bg-black/40 px-3 py-1 rounded-full border border-white/5 uppercase tracking-widest">{msg.meta.provider} • {msg.meta.model}</span>
                {typeof msg.meta.nativeSearch === "boolean" && (
                  <span className={`px-3 py-1 rounded-full border uppercase tracking-widest ${msg.meta.nativeSearch ? "bg-emerald-500/10 text-emerald-300 border-emerald-400/20" : "bg-white/5 text-[var(--text-muted)] border-white/10"}`}>
                    WEB {msg.meta.nativeSearch ? "ON" : "OFF"} {msg.meta.nativeSearchMode ? `• ${msg.meta.nativeSearchMode}` : ""}
                  </span>
                )}
                {msg.meta.safetyMode && (
                  <span className={`px-3 py-1 rounded-full border uppercase tracking-widest ${msg.meta.safetyMode === "dev-unsafe" ? "bg-red-500/10 text-red-300 border-red-400/20" : "bg-amber-400/10 text-amber-200 border-amber-300/20"}`}>
                    SAFE {msg.meta.safetyMode}
                  </span>
                )}
                {msg.meta.tokens && <span className="bg-[var(--purple-dark)] text-[var(--purple-neon)] px-3 py-1 rounded-full border border-[var(--purple-neon)]/20">{msg.meta.tokens} TOKENS</span>}
              </div>
            )}

            {/* Timeline única de "pensando": texto + chamadas de ferramenta juntos.
                O 3o caso e o provider que NAO streama (Gemini): o raciocinio chega
                pronto no meta em vez de token a token. */}
            {msg.thinking?.length ? (
              <ThinkingRenderer items={msg.thinking} isThinking={false} elapsedMs={msg.thinkingElapsedMs} />
            ) : msg.id === "streaming-res" && liveThinking.length > 0 ? (
              <ThinkingRenderer items={liveThinking} isThinking={true} />
            ) : msg.meta?.thinking?.length ? (
              <ThinkingRenderer items={msg.meta.thinking} isThinking={false} elapsedMs={msg.thinkingElapsedMs} />
            ) : null}

            {/* Agent Mode: só pra planos reais (Agent Core/imagem), a timeline acima já cobre o resto */}
            {planHasRealSteps(msg.agentPlan) && msg.agentPlan && <AgentPlanRenderer plan={msg.agentPlan} active={msg.id === "streaming-res" && isTyping} />}

            {msg.meta?.memoryContext?.memories?.length ? (
              <MemoryContextRenderer memoryContext={msg.meta.memoryContext} />
            ) : null}

            {/* Fallback pra histórico recarregado (sem timeline ao vivo salva) */}
            {!msg.thinking?.length && msg.meta?.toolRuns?.length ? (
              <ToolRunsRenderer toolRuns={msg.meta.toolRuns} />
            ) : null}

            {(msg.meta?.grounding?.queries?.length || msg.meta?.grounding?.sources?.length) ? (
              <SearchSourcesRenderer grounding={msg.meta.grounding} />
            ) : null}

            <div className="prose prose-invert prose-sm max-w-none prose-p:leading-relaxed prose-pre:bg-black/50 prose-pre:border prose-pre:border-white/10 prose-code:text-[var(--cyan-neon)] prose-a:text-[var(--cyan-neon)] prose-a:no-underline hover:prose-a:underline">
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                components={{
                  a: ({node, ...props}) => <a {...props} target="_blank" rel="noreferrer" className="flex items-center gap-1 inline-flex" />
                }}
              >
                {renderMessageContent(msg)}
              </ReactMarkdown>
            </div>

            {msg.meta?.providerError ? (
              <ErrorDetailRenderer error={msg.meta.providerError} />
            ) : null}

            {msg.content.length > LONG_MESSAGE_LIMIT && (
              <button
                onClick={() => onToggleExpand(msg.id)}
                className="mt-3 text-[10px] font-black uppercase tracking-widest text-[var(--cyan-neon)] hover:text-white"
              >
                {isExpanded ? "Ver menos" : "Ver mais"}
              </button>
            )}

            {/* Renderização de Mídias */}
            {msg.media && msg.media.map((m, i) => (
              <MediaRenderer
                key={`${m.job_id || m.url || "media"}-${i}`}
                media={m}
                onOpenImage={onOpenImage}
                onDelete={() => onDeleteMedia(msg.id, i)}
                onReSynthesize={() => onGenerateSpeech(msg.id, msg.content)}
              />
            ))}

            {/* Action Buttons Footer */}
            <div className="mt-3 opacity-0 group-hover/hana:opacity-100 transition-all duration-300 flex items-center gap-3">
              <button
                onClick={() => onGenerateSpeech(msg.id, msg.content)}
                className="text-[10px] font-bold uppercase tracking-widest bg-white/5 hover:bg-[var(--purple-dark)] text-[var(--text-secondary)] hover:text-white px-4 py-2 rounded-full border border-white/5 transition-all flex items-center gap-2"
              >
                <Volume2 size={12} /> Gerar voz
              </button>
              <button
                onClick={() => navigator.clipboard?.writeText(msg.content)}
                className="text-[10px] font-bold uppercase tracking-widest bg-white/5 hover:bg-[var(--purple-dark)] text-[var(--text-secondary)] hover:text-white px-4 py-2 rounded-full border border-white/5 transition-all flex items-center gap-2"
              >
                <Copy size={12} /> Copiar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

interface ChatMessageListProps {
  visibleMessages: ChatMessage[];
  hiddenMessages: number;
  onShowFullHistory: () => void;
  renderMessageContent: (msg: ChatMessage) => string;
  expandedMessages: Record<string, boolean>;
  onToggleExpand: (msgId: string) => void;
  onDeleteMessage: (msgId: string) => void;
  onDeleteMedia: (msgId: string, mediaIndex: number) => void;
  onGenerateSpeech: (msgId: string, content: string) => void;
  onOpenImage: (url: string) => void;
  identity: { name: string; avatar?: string };
  isTyping: boolean;
  liveThinking: ThinkingItem[];
  liveActivity: { label: string; detail: string };
  onPickStarterPrompt: (prompt: string) => void;
  showScrollToBottom: boolean;
  onScrollToBottom: () => void;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  contentRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  onWheel: (e: React.WheelEvent<HTMLDivElement>) => void;
  onPointerDown: () => void;
  onPointerUp: () => void;
  onPointerCancel: () => void;
}

/** Scrollable message area with all renderers, scroll-to-bottom button, and live activity indicator. */
export function ChatMessageList({
  visibleMessages,
  hiddenMessages,
  onShowFullHistory,
  renderMessageContent,
  expandedMessages,
  onToggleExpand,
  onDeleteMessage,
  onDeleteMedia,
  onGenerateSpeech,
  onOpenImage,
  identity,
  isTyping,
  liveThinking,
  liveActivity,
  onPickStarterPrompt,
  showScrollToBottom,
  onScrollToBottom,
  scrollRef,
  contentRef,
  onScroll,
  onWheel,
  onPointerDown,
  onPointerUp,
  onPointerCancel,
}: ChatMessageListProps) {
  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        className="relative h-full overflow-y-auto p-6 custom-scrollbar"
      >
      <div ref={contentRef} className="mx-auto max-w-6xl space-y-8 pt-24">

      {hiddenMessages > 0 && (
        <div className="flex justify-center">
          <button
            onClick={onShowFullHistory}
            className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-white hover:border-[var(--cyan-neon)]/40 transition-colors"
          >
            <ChevronDown size={12} /> Mostrar {hiddenMessages} mensagens antigas
          </button>
        </div>
      )}

      {visibleMessages.map((msg) => (
        <ChatMessageRow
          key={msg.id}
          msg={msg}
          renderMessageContent={renderMessageContent}
          isExpanded={Boolean(expandedMessages[msg.id])}
          onToggleExpand={onToggleExpand}
          onDeleteMessage={onDeleteMessage}
          onDeleteMedia={onDeleteMedia}
          onGenerateSpeech={onGenerateSpeech}
          onOpenImage={onOpenImage}
          identity={identity}
          isTyping={msg.id === "streaming-res" ? isTyping : false}
          liveThinking={msg.id === "streaming-res" ? liveThinking : EMPTY_THINKING}
        />
      ))}

      {/* Conversa ainda sem nenhuma troca real (so a mensagem de boas-vindas do
          sistema): oferece atalhos em vez de deixar a tela em branco. */}
      {!isTyping && !visibleMessages.some((msg) => msg.role === "user" || msg.role === "hana") && (
        <StarterPrompts onPick={onPickStarterPrompt} />
      )}

      {isTyping && liveActivity.label && (
        <div className="sticky bottom-3 z-20 flex w-full justify-start animate-fade-in pointer-events-none">
          <div className="max-w-[620px] rounded-lg border border-fuchsia-400/25 bg-black/85 px-4 py-3 shadow-[0_0_24px_rgba(236,72,153,0.12)] backdrop-blur-xl">
            <div className="flex items-center gap-3">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-fuchsia-400/30 bg-fuchsia-500/10">
                <Bot size={14} className="text-fuchsia-300 animate-pulse" />
              </div>
              <div className="min-w-0 flex-1">
                <span className="block text-[10px] font-black uppercase tracking-widest text-fuchsia-300">{liveActivity.label}</span>
                {liveActivity.detail ? (
                  <span className="block truncate text-[11px] text-[var(--text-muted)]">{liveActivity.detail}</span>
                ) : (
                  <span className="inline-block h-3 w-[7px] translate-y-[2px] animate-[blink-cursor_1s_step-end_infinite] bg-fuchsia-300/80" />
                )}
              </div>
              <div className="flex items-center gap-1">
                {[0, 120, 240].map((delay) => (
                  <div key={delay} className="h-1.5 w-1.5 rounded-full bg-fuchsia-300 animate-bounce" style={{ animationDelay: `${delay}ms` }} />
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
      </div>
      </div>

      {showScrollToBottom && (
        <button
          type="button"
          onClick={onScrollToBottom}
          className="absolute bottom-5 right-5 z-40 flex h-11 items-center gap-2 rounded-full border border-[var(--cyan-neon)]/40 bg-[#071217]/95 px-3 text-[var(--cyan-neon)] shadow-[0_0_22px_rgba(34,211,238,0.22)] backdrop-blur-md transition-all hover:scale-105 hover:bg-[#0b2028]"
          title="Ir para a mensagem mais recente"
          aria-label="Ir para a mensagem mais recente"
        >
          <ChevronDown size={18} />
          <span className="text-[10px] font-black uppercase tracking-widest">Mais recente</span>
        </button>
      )}
    </div>
  );
}
