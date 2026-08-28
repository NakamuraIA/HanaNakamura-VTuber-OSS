import {
  X, Terminal, Globe2, ShieldCheck, Volume2, VolumeX, BrainCircuit,
} from "lucide-react";
import { ChatSession, SafetyMode, ChatConfig, LlmConfig, OpenRouterRoutingConfig } from "../../../models/types";
import { CatalogPicker, CatalogPickerOption } from "../shared/CatalogPicker";
import { Button } from "../shared/Button";
import { OpenRouterEndpointPicker, DEFAULT_OPENROUTER_ROUTING } from "../shared/OpenRouterEndpointPicker";
import { HistoricoBanco } from "./HistoricoBanco";
import type { ChatMessage } from "../../../models/types";
import { DEEPSEEK_REASONING_LEVELS, OPENROUTER_REASONING_LEVELS } from "../../pages/TabLLM";

const SAFETY_MODES: { id: SafetyMode; label: string }[] = [
  { id: "safe", label: "Safe" },
  { id: "assisted", label: "Assisted" },
  { id: "trusted", label: "Trusted" },
  { id: "dev-unsafe", label: "Dev Unsafe" },
];

const TYPING_SPEED_ORDER: TypingSpeed[] = ["slow", "normal", "fast", "instant"];
const TYPING_SPEED_LABEL: Record<TypingSpeed, string> = { slow: "Lenta", normal: "Normal", fast: "Rapida", instant: "Instantanea" };
type TypingSpeed = "slow" | "normal" | "fast" | "instant";

interface ChatConfigModalProps {
  showConfig: boolean;
  onClose: () => void;
  provider: string;
  model: string;
  llmProviders: string[];
  modelPickerOptions: CatalogPickerOption[];
  selectChatProvider: (p: string) => void;
  setModel: (m: string) => void;
  providerHasWebSearch: boolean;
  nativeSearchMode: "auto" | "force" | "off";
  setNativeSearchMode: (m: "auto" | "force" | "off") => void;
  safetyMode: SafetyMode;
  setSafetyMode: (m: SafetyMode) => void;
  autoTtsEnabled: boolean;
  setAutoTtsEnabled: React.Dispatch<React.SetStateAction<boolean>>;
  showTypingSpeed: boolean;
  setShowTypingSpeed: React.Dispatch<React.SetStateAction<boolean>>;
  typingSpeed: TypingSpeed;
  setTypingSpeed: React.Dispatch<React.SetStateAction<TypingSpeed>>;
  activeSessionId: string;
  chatSessions: ChatSession[];
  switchChatSession: (id: string) => void;
  startNewChat: () => void;
  clearCurrentChat: () => void;
  deleteChatSession: (id: string) => void;
  openrouterRoutingByModel: ChatConfig["openrouterRoutingByModel"];
  setOpenrouterRoutingByModel: React.Dispatch<React.SetStateAction<ChatConfig["openrouterRoutingByModel"]>>;
  thinkingConfig: LlmConfig | null;
  onUpdateThinking: (patch: Partial<LlmConfig>) => void;
  /** Importa uma conversa do banco pra uma sessao local nova. */
  onImportarDoBanco: (titulo: string, mensagens: ChatMessage[]) => void;
}

/** Full-screen config modal with Engine (provider+model), Behavior (search/safety/TTS/typing), and Sessions. */
export function ChatConfigModal({
  showConfig,
  onClose,
  provider,
  model,
  llmProviders,
  modelPickerOptions,
  selectChatProvider,
  setModel,
  providerHasWebSearch,
  nativeSearchMode,
  setNativeSearchMode,
  safetyMode,
  setSafetyMode,
  autoTtsEnabled,
  setAutoTtsEnabled,
  showTypingSpeed,
  setShowTypingSpeed,
  typingSpeed,
  setTypingSpeed,
  activeSessionId,
  chatSessions,
  switchChatSession,
  startNewChat,
  clearCurrentChat,
  deleteChatSession,
  openrouterRoutingByModel,
  setOpenrouterRoutingByModel,
  thinkingConfig,
  onUpdateThinking,
  onImportarDoBanco,
}: ChatConfigModalProps) {
  if (!showConfig) return null;

  // "Pensar antes de falar": groq/qwen sao toggle on-off; deepseek/openrouter sao
  // slider de esforco (mesma escala usada na aba Cerebro, mesmo llm_config no
  // backend — mudar aqui ou la afeta o mesmo turno).
  const thinkingToggleField = provider === "groq" ? "groqThinking" : provider === "qwen" ? "qwenThinking" : null;
  const thinkingEffortField = provider === "deepseek" ? "deepseekReasoningEffort" : provider === "openrouter" ? "openrouterReasoningEffort" : null;
  const thinkingLevels = provider === "deepseek" ? DEEPSEEK_REASONING_LEVELS : OPENROUTER_REASONING_LEVELS;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#141419]/70 shadow-2xl backdrop-blur-sm"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
          <h3 className="text-sm font-black uppercase tracking-widest text-[var(--text-primary)]">Configuracoes do Chat</h3>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-white" title="Fechar">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-2 overflow-y-auto p-4">
        {/* SECAO: MOTOR (provider + modelo) */}
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 rounded-lg border border-[var(--purple-neon)]/20 bg-[var(--purple-neon)]/5 px-2.5 py-1.5 transition-colors hover:border-[var(--purple-neon)]/40">
              <Terminal size={13} className="text-[var(--purple-neon)]" />
              <select
                className="cursor-pointer bg-transparent font-mono text-[11px] font-bold uppercase text-[var(--text-primary)] outline-none [&>option]:bg-[#0f0f13]"
                value={provider}
                onChange={(e) => selectChatProvider(e.target.value)}
              >
                {llmProviders.map((p) => <option key={p} value={p} className="bg-[#0f0f13]">{p}</option>)}
              </select>
            </div>
            <div className="flex min-w-[260px] flex-1 items-center gap-2">
              <BrainCircuit size={14} className="shrink-0 text-[var(--cyan-neon)]" />
              <div className="min-w-0 flex-1">
                <CatalogPicker
                  value={model}
                  options={modelPickerOptions}
                  onChange={setModel}
                  favoriteNamespace={`chat-llm:${provider}`}
            modal
                  placeholder="Selecione um modelo"
                  searchPlaceholder="Buscar modelo por nome ou ID..."
                  emptyMessage="Nenhum modelo deste provider corresponde aos filtros."
                  accent="cyan"
                  compact
                />
              </div>
            </div>
          </div>
          {provider === "openrouter" && (
            <OpenRouterEndpointPicker
              model={model}
              value={openrouterRoutingByModel?.[model] || DEFAULT_OPENROUTER_ROUTING}
              onChange={(routing: OpenRouterRoutingConfig) => setOpenrouterRoutingByModel((current) => ({ ...current, [model]: routing }))}
              compact
            />
          )}
          {provider === "qwen" && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--purple-neon)]/20 bg-[var(--purple-neon)]/5 px-2.5 py-1.5">
              <span className="font-mono text-[11px] font-bold uppercase text-[var(--text-secondary)]">Região</span>
              <select
                className="cursor-pointer bg-transparent font-mono text-[11px] font-bold uppercase text-[var(--text-primary)] outline-none [&>option]:bg-[#0f0f13]"
                value={thinkingConfig?.qwenRegion || "virginia"}
                onChange={(event) => onUpdateThinking({
                  qwenRegion: event.target.value === "singapore" ? "singapore" : "virginia",
                })}
                title="Usa a chave e o endpoint configurados para a região escolhida."
              >
                <option value="virginia" className="bg-[#0f0f13]">Virgínia</option>
                <option value="singapore" className="bg-[#0f0f13]">Singapura</option>
              </select>
            </div>
          )}
        </div>

        {/* SECAO: COMPORTAMENTO */}
        <div className="flex flex-col gap-2 border-t border-white/5 pt-2">
          <div className="flex flex-wrap items-center gap-2">
            {providerHasWebSearch ? (
              <div className="flex items-center gap-1.5 rounded-lg border border-emerald-400/15 bg-emerald-500/5 px-2.5 py-1.5 transition-colors hover:border-emerald-400/30">
                <Globe2 size={13} className="text-emerald-300" />
                <select
                  className="cursor-pointer bg-transparent font-mono text-[11px] font-bold uppercase text-[var(--text-primary)] outline-none [&>option]:bg-[#0f0f13]"
                  value={nativeSearchMode}
                  onChange={(e) => setNativeSearchMode(e.target.value as "auto" | "force" | "off")}
                  title={provider === "gemini_api" ? "Grounding nativo com Google Search" : "Pesquisa web do OpenRouter (plugin web, cobrado por busca)"}
                >
                  <option value="auto" className="bg-[#0f0f13]">Web auto</option>
                  <option value="force" className="bg-[#0f0f13]">Web on</option>
                  <option value="off" className="bg-[#0f0f13]">Web off</option>
                </select>
              </div>
            ) : (
              <span
                className="flex items-center gap-1.5 rounded-lg border border-emerald-400/20 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] font-bold text-emerald-200"
                title="Este provider pesquisa na web pela ferramenta Tavily (MCP) quando o modelo suporta tools. Ative o Tavily na aba MCP."
              >
                <Globe2 size={13} />
                Web via Tavily
              </span>
            )}

            <div className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 transition-colors ${
              safetyMode === "dev-unsafe"
                ? "bg-red-500/15 border-red-400/30"
                : "bg-amber-500/5 border-amber-400/15 hover:border-amber-400/30"
            }`}>
              <ShieldCheck size={13} className={safetyMode === "dev-unsafe" ? "text-red-300" : "text-amber-200"} />
              <select
                className="cursor-pointer bg-transparent font-mono text-[11px] font-bold uppercase text-[var(--text-primary)] outline-none [&>option]:bg-[#0f0f13]"
                value={safetyMode}
                onChange={(e) => setSafetyMode(e.target.value as SafetyMode)}
                title="Modo de seguranca para tools do Agent Mode"
              >
                {SAFETY_MODES.map((mode) => (
                  <option key={mode.id} value={mode.id} className="bg-[#0f0f13]">{mode.label}</option>
                ))}
              </select>
            </div>

            {thinkingToggleField && (
              <button
                type="button"
                onClick={() => onUpdateThinking({ [thinkingToggleField]: !(thinkingConfig?.[thinkingToggleField] ?? true) })}
                className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-black uppercase tracking-wider transition-colors ${
                  (thinkingConfig?.[thinkingToggleField] ?? true)
                    ? "border-[var(--purple-neon)]/30 bg-[var(--purple-neon)]/15 text-[var(--purple-neon)]"
                    : "border-white/10 bg-white/5 text-[var(--text-muted)] hover:text-white"
                }`}
                title="Pensar antes de falar (raciocinio do modelo)"
              >
                <BrainCircuit size={14} />
                Pensar {(thinkingConfig?.[thinkingToggleField] ?? true) ? "on" : "off"}
              </button>
            )}

            {thinkingEffortField && (
              <div
                className="flex items-center gap-1.5 rounded-lg border border-[var(--purple-neon)]/20 bg-[var(--purple-neon)]/5 px-2.5 py-1.5"
                title="Esforco de raciocinio do modelo"
              >
                <BrainCircuit size={13} className="text-[var(--purple-neon)]" />
                <select
                  className="cursor-pointer bg-transparent font-mono text-[11px] font-bold uppercase text-[var(--text-primary)] outline-none [&>option]:bg-[#0f0f13]"
                  value={thinkingConfig?.[thinkingEffortField] || (provider === "deepseek" ? "high" : "")}
                  onChange={(e) => onUpdateThinking({ [thinkingEffortField]: e.target.value })}
                >
                  {thinkingLevels.map((lvl) => (
                    <option key={lvl.value} value={lvl.value} className="bg-[#0f0f13]">Pensar: {lvl.label}</option>
                  ))}
                </select>
              </div>
            )}

            <button
              type="button"
              onClick={() => setAutoTtsEnabled((value: boolean) => !value)}
              className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-black uppercase tracking-wider transition-colors ${
                autoTtsEnabled
                  ? "border-pink-300/30 bg-pink-500/15 text-pink-200"
                  : "border-white/10 bg-white/5 text-[var(--text-muted)] hover:text-white"
              }`}
              title="Gerar audio TTS automaticamente para novas respostas da Hana"
            >
              {autoTtsEnabled ? <Volume2 size={14} /> : <VolumeX size={14} />}
              TTS {autoTtsEnabled ? "on" : "off"}
            </button>

            {showTypingSpeed && (
              <button
                type="button"
                onClick={() => setTypingSpeed((prev: TypingSpeed) => TYPING_SPEED_ORDER[(TYPING_SPEED_ORDER.indexOf(prev) + 1) % TYPING_SPEED_ORDER.length])}
                className="flex items-center gap-1.5 rounded-lg border border-cyan-300/30 bg-cyan-500/15 px-2.5 py-1.5 text-[11px] font-black uppercase tracking-wider text-cyan-200 transition-colors hover:bg-cyan-500/25"
                title="Velocidade da digitacao da Hana (clique para alternar)"
              >
                <Terminal size={14} />
                {TYPING_SPEED_LABEL[typingSpeed]}
              </button>
            )}

            <button
              type="button"
              onClick={() => setShowTypingSpeed((value: boolean) => !value)}
              className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-black uppercase tracking-wider transition-colors ${
                showTypingSpeed
                  ? "border-cyan-300/30 bg-cyan-500/15 text-cyan-200"
                  : "border-white/10 bg-white/5 text-[var(--text-muted)] hover:text-white"
              }`}
              title="Mostrar ou esconder o botao de velocidade de digitacao no chat"
            >
              <Terminal size={14} />
              Botao velocidade {showTypingSpeed ? "on" : "off"}
            </button>
          </div>
        </div>

        {/* SECAO: CONVERSAS */}
        <div className="flex flex-col gap-2 border-t border-white/5 pt-2">
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={activeSessionId}
              onChange={(event) => switchChatSession(event.target.value)}
              className="min-w-[180px] max-w-[300px] flex-1 cursor-pointer rounded-lg border border-white/10 bg-black/40 px-2.5 py-1.5 text-[11px] font-bold text-[var(--text-primary)] outline-none [&>option]:bg-[#0f0f13]"
              title="Historico local de conversas"
            >
              {chatSessions.map((session) => (
                <option key={session.id} value={session.id} className="bg-[#0f0f13]">
                  {session.title}
                </option>
              ))}
            </select>
            <Button onClick={startNewChat} variant="secondary" size="sm">Nova</Button>
            <Button onClick={clearCurrentChat} variant="success" size="sm">Limpar</Button>
            <Button onClick={() => deleteChatSession(activeSessionId)} variant="danger" size="sm">Apagar</Button>
          </div>
          <HistoricoBanco onImportar={onImportarDoBanco} />
        </div>
        </div>
      </div>
    </div>
  );
}
