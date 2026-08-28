import {
  Send, Paperclip, Mic, StopCircle, Loader2,
} from "lucide-react";
import { ChatAttachment } from "../../../models/types";
import { fileIconFor } from "./chatUtils";

/** Returns an icon component for the given attachment MIME type. */
function fileIconElement(type: string) {
  const icon = fileIconFor(type);
  return icon;
}

interface ChatInputBarProps {
  input: string;
  onInputChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  onPaste: (e: React.ClipboardEvent) => void;
  onSend: () => void;
  isTyping: boolean;
  isRecording: boolean;
  isTranscribing: boolean;
  onToggleRecording: () => void;
  onFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  attachments: ChatAttachment[];
  onRemoveAttachment: (index: number) => void;
  identity: { name: string };
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

/** Bottom input bar with mic/recording, attach, textarea, and send button. */
export function ChatInputBar({
  input,
  onInputChange,
  onKeyDown,
  onPaste,
  onSend,
  isTyping,
  isRecording,
  isTranscribing,
  onToggleRecording,
  onFileUpload,
  attachments,
  onRemoveAttachment,
  identity,
  inputRef,
}: ChatInputBarProps) {
  return (
    <div className="z-10 relative px-7 pt-3 pb-5">
      
      <div className="flex items-end gap-4 max-w-6xl mx-auto">
        <div className="flex gap-2 mb-1 shrink-0">
          <button
            type="button"
            onClick={onToggleRecording}
            disabled={isTranscribing}
            className={`w-12 h-12 flex items-center justify-center rounded-2xl border transition-all shadow-lg group ${
              isRecording
                ? "bg-red-500/20 border-red-400/40 text-red-200 animate-pulse"
                : "bg-white/5 hover:bg-[var(--purple-dark)] border-white/5 hover:border-[var(--purple-neon)]/30 text-[var(--text-secondary)] hover:text-[var(--purple-neon)]"
            } disabled:opacity-50`}
            title={isRecording ? "Parar gravacao" : "Gravar voz para preencher o texto"}
          >
            {isTranscribing ? <Loader2 size={20} className="animate-spin" /> : (isRecording ? <StopCircle size={20} /> : <Mic size={20} className="group-hover:scale-110 transition-transform" />)}
          </button>
          
          <label className="w-12 h-12 flex items-center justify-center rounded-2xl bg-white/5 hover:bg-blue-500/10 border border-white/5 hover:border-blue-500/30 text-[var(--text-secondary)] hover:text-blue-400 transition-all shadow-lg cursor-pointer group">
            <Paperclip size={20} className="group-hover:rotate-45 transition-transform" />
            <input type="file" className="hidden" multiple accept="image/*,audio/*,video/*,application/pdf,text/plain,text/markdown,application/json,.txt,.md,.pdf,.mp3,.wav,.ogg,.mp4,.webm,.gif" onChange={onFileUpload} />
          </label>
        </div>

        <div className="flex-1 bg-[rgba(0,0,0,0.5)] border border-[var(--border-strong)] rounded-[1.5rem] p-1.5 relative group focus-within:border-[var(--purple-neon)] focus-within:shadow-[0_0_40px_rgba(168,85,247,0.2)] transition-all duration-500 shadow-2xl flex flex-col">
          
          {/* Preview de Anexos dentro da caixa de texto */}
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 p-3 pb-0 animate-fade-in">
              {attachments.map((att, i) => (
                <div key={i} className="group/att relative w-12 h-12 rounded-lg border border-[var(--purple-neon)]/30 overflow-hidden shadow-lg">
                  {att.type.startsWith("image/") ? (
                    <img src={att.data} loading="lazy" className="w-full h-full object-cover" alt="preview" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-[var(--cyan-neon)] bg-black/30">
                      {fileIconElement(att.type)}
                    </div>
                  )}
                  <button 
                    onClick={() => onRemoveAttachment(i)}
                    className="absolute top-0.5 right-0.5 bg-red-500 rounded-full w-4 h-4 flex items-center justify-center text-white text-[10px] font-bold opacity-0 group-hover/att:opacity-100 transition-opacity"
                  >
                    x
                  </button>
                </div>
              ))}
            </div>
          )}

          <textarea 
            ref={inputRef}
            value={input}
            onChange={onInputChange}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            className="w-full bg-transparent text-[var(--text-primary)] text-[15px] resize-none outline-none custom-scrollbar p-3 pl-5 max-h-60 min-h-[54px] font-medium placeholder:text-[var(--text-muted)] leading-relaxed"
            placeholder={attachments.length > 0 ? "Adicione uma descricao para os anexos..." : `Fale com a ${identity.name}... (Ou arraste arquivos para aqui)`}
            rows={1}
          />
        </div>

        <button 
          onClick={onSend}
          disabled={(!input.trim() && attachments.length === 0) || isTyping}
          className="w-[60px] h-[60px] bg-gradient-to-br from-[var(--purple-neon)] to-[#7e22ce] hover:brightness-110 disabled:from-gray-800 disabled:to-gray-900 text-white disabled:text-gray-600 rounded-[1.2rem] flex items-center justify-center transition-all shadow-[0_10px_25px_rgba(168,85,247,0.4)] hover:shadow-[0_15px_35px_rgba(168,85,247,0.6)] active:scale-90 shrink-0 mb-0.5 border border-white/10"
        >
          <Send size={24} />
        </button>
      </div>
      
    </div>
  );
}
