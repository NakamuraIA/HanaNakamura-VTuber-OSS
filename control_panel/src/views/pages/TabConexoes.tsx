import type { ReactNode } from "react";
import { PlugZap, Mic, Eye, MessageSquareText, ShieldAlert, Keyboard, Bot } from "lucide-react";
import { useConnections } from "../../hooks/useConnections";
import { ConnectionsConfig } from "../../models/types";
import { ModuleToggleCard } from "../components/shared/ModuleToggleCard";
import { TabHeader } from "../components/shared/TabHeader";

const HOTKEYS = [
  "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
  "CapsLock", "ScrollLock", "Insert", "Home", "End", "PageUp", "PageDown",
];

type ModuleConfig = {
  id: keyof ConnectionsConfig;
  title: string;
  description: string;
  icon: ReactNode;
  neonColor: string;
  hotkey?: "pttKey" | "stopKey";
};

const MODULES: ModuleConfig[] = [
  {
    id: "tts",
    title: "Sintese de Voz (TTS)",
    description: "Slot opcional de fala. Fica visivel no painel, mas so executa quando a integracao estiver instalada.",
    icon: <Mic size={24} />,
    neonColor: "blue",
  },
  {
    id: "stt",
    title: "Reconhecimento de Voz (STT)",
    description: "Entrada por microfone no backend. Quando ligado, o runtime aplica a configuracao em tempo real.",
    icon: <Mic size={24} />,
    neonColor: "purple",
  },
  {
    id: "vad",
    title: "Detector de Voz (VAD)",
    description: "Controla o sempre ouvindo. Se desligar, a fala entra apenas por PTT ou teste manual.",
    icon: <Mic size={24} />,
    neonColor: "cyan",
  },
  {
    id: "ptt",
    title: "Pressione para Falar (PTT)",
    description: "Hotkey global no backend para gravar somente enquanto a tecla estiver pressionada.",
    icon: <Keyboard size={24} />,
    neonColor: "cyan",
    hotkey: "pttKey",
  },
  {
    id: "stopHotkey",
    title: "Parar Resposta (Hotkey)",
    description: "Hotkey global de emergencia para interromper resposta ou midia quando a integracao estiver ativa.",
    icon: <ShieldAlert size={24} />,
    neonColor: "red",
    hotkey: "stopKey",
  },
  {
    id: "visao",
    title: "Visao sob demanda",
    description: "So no Terminal Agente e na voz: a Hana captura sua tela sozinha quando o modelo suporta imagem. No Chat do Controle a visao e so por anexo manual (colar/arrastar imagem).",
    icon: <Eye size={24} />,
    neonColor: "purple",
  },
  {
    id: "discord",
    title: "Bot do Discord",
    description: "Transporte externo para texto e voz. O bot roda separado e usa o backend local da Hana.",
    icon: <MessageSquareText size={24} />,
    neonColor: "blue",
  },
  {
    id: "localHands",
    title: "Mãos (Terminal)",
    description: "Permite a Hana rodar comandos e mexer em arquivos no seu PC. Ações perigosas (deletar, admin) pedem sua confirmação antes.",
    icon: <Bot size={24} />,
    neonColor: "cyan",
  },
];

export function TabConexoes() {
  const { config, toggleField, updateKey, audioHover } = useConnections();

  if (!config) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--cyan-neon)]" />
      </div>
    );
  }

  return (
    <div className="w-full h-full bg-[var(--bg-sidebar)] backdrop-blur-2xl p-8 overflow-y-auto custom-scrollbar shadow-2xl relative transition-all duration-500">
      <TabHeader
        icon={<PlugZap size={24} />}
        title="Conexoes & Modulos"
        subtitle="Sentidos e integracoes opcionais da Hana"
      />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 pb-10">
        {MODULES.map((item) => (
          <ModuleToggleCard
            key={String(item.id)}
            isActive={Boolean(config[item.id])}
            title={item.title}
            description={item.description}
            icon={item.icon}
            neonColor={item.neonColor}
            hasHotkey={Boolean(item.hotkey)}
            hotkeyValue={item.hotkey ? String(config[item.hotkey]) : undefined}
            hotkeysList={HOTKEYS}
            onToggle={() => toggleField(item.id)}
            onUpdateKey={item.hotkey ? (value) => updateKey(item.hotkey!, value) : undefined}
            onHover={audioHover}
          >
            {item.id === "discord" && (
              <div className="space-y-2">
                <p className="text-xs text-[var(--text-muted)]">
                  Ligar aqui sobe o bot automaticamente. Chatbot de texto privado:
                  use <span className="font-mono text-cyan-300">/hana</span>, ou fale no
                  PV / mencione (@Hana). Só a Operador tem acesso.
                </p>
              </div>
            )}
          </ModuleToggleCard>
        ))}
      </div>
    </div>
  );
}