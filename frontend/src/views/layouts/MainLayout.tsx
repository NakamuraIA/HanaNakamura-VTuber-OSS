import { lazy, Suspense, useEffect, useState } from "react";
import { Sidebar } from "./Sidebar";
import { MenuOption } from "../../models/types";

// Importing icons
import {
  MonitorDot, BrainCircuit, Database, MessageSquareText,
  Cable, Paintbrush, ScrollText, Network, TerminalSquare
} from "lucide-react";

import { CyberBackground } from "../components/CyberBackground";
import { ReminderToasts } from "../components/shared/ReminderToasts";

// Lazy-loaded tab components — each loads only when first accessed
const TabGeral = lazy(() => import("../pages/TabGeral").then(m => ({ default: m.TabGeral })));
const TabLLM = lazy(() => import("../pages/TabLLM").then(m => ({ default: m.TabLLM })));
const TabPersonalizacao = lazy(() => import("../pages/TabPersonalizacao").then(m => ({ default: m.TabPersonalizacao })));
const TabChat = lazy(() => import("../pages/TabChat").then(m => ({ default: m.TabChat })));
const TabConexoes = lazy(() => import("../pages/TabConexoes").then(m => ({ default: m.TabConexoes })));
const TabMemoria = lazy(() => import("../pages/TabMemoria").then(m => ({ default: m.TabMemoria })));
const TabLogs = lazy(() => import("../pages/TabLogs").then(m => ({ default: m.TabLogs })));
const TabMCP = lazy(() => import("../pages/TabMCP").then(m => ({ default: m.TabMCP })));
const TabTerminalAgent = lazy(() => import("../pages/TabTerminalAgent").then(m => ({ default: m.TabTerminalAgent })));

/** Skeleton placeholder shown while a tab is loading. */
function TabSkeleton() {
  return (
    <div className="w-full h-full bg-[var(--bg-sidebar)] hana-glass p-8 flex items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <div className="w-10 h-10 border-2 border-[var(--accent)]/30 border-t-[var(--accent)] rounded-full animate-spin" />
        <span className="text-sm text-[var(--text-muted)] font-mono">carregando...</span>
      </div>
    </div>
  );
}

const menus: MenuOption[] = [
  { icon: <MonitorDot size={20} />, label: "Monitor Geral", id: "geral" },
  { icon: <BrainCircuit size={20} />, label: "Cérebro", id: "llm" },
  { icon: <Database size={20} />, label: "Memória", id: "memoria" },
  { icon: <MessageSquareText size={20} />, label: "Chat do Controle", id: "chat" },
  { icon: <TerminalSquare size={20} />, label: "Terminal Agente", id: "terminal-agente" },
  { icon: <Cable size={20} />, label: "Conexões", id: "conexoes" },
  { icon: <Network size={20} />, label: "MCP", id: "mcp" },
  { icon: <Paintbrush size={20} />, label: "Personalização", id: "personalizacao" },
  { icon: <ScrollText size={20} />, label: "Logs", id: "logs" },
];

/** Map tab id → lazy component (with isActive prop where needed). */
function getTabComponent(tab: string) {
  switch (tab) {
    case "geral": return <TabGeral />;
    case "llm": return <TabLLM />;
    case "personalizacao": return <TabPersonalizacao />;
    case "terminal-agente": return <TabTerminalAgent isActive={true} />;
    case "conexoes": return <TabConexoes />;
    case "mcp": return <TabMCP />;
    case "memoria": return <TabMemoria />;
    case "logs": return <TabLogs />;
    default: return null;
  }
}

export function MainLayout() {
  const [activeTab, setActiveTab] = useState("geral");

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ tab?: string }>).detail;
      if (detail?.tab) setActiveTab(detail.tab);
    };
    window.addEventListener("hana:navigate-tab", handler);
    return () => window.removeEventListener("hana:navigate-tab", handler);
  }, []);

  return (
    <div className="flex h-screen w-full text-[var(--text-primary)] bg-transparent">
      <CyberBackground />
      <ReminderToasts />
      <Sidebar menus={menus} activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Main Content */}
      <div className="flex-1 h-full overflow-hidden relative p-0">
        {/* Atmospheric background lights (very subtle). */}
        <div className="absolute top-[-10%] right-[-5%] w-[500px] h-[500px] bg-slate-500 rounded-full blur-[160px] opacity-[0.03] pointer-events-none" />
        <div className="absolute bottom-[-10%] left-[20%] w-[400px] h-[400px] bg-slate-500 rounded-full blur-[160px] opacity-[0.03] pointer-events-none" />

        {/* O Chat permanece montado quando fica oculto. Assim, uma pesquisa ou
            ferramenta em andamento continua recebendo o WebSocket enquanto a
            Nakamura consulta outra aba. O proprio TabChat usa isActive para
            pausar apenas efeitos visuais, como o scroll automatico. */}
        <div className={activeTab === "chat" ? "w-full h-full relative z-10 animate-tab-in" : "hidden"}>
          <Suspense fallback={<TabSkeleton />}>
            <TabChat isActive={activeTab === "chat"} />
          </Suspense>
        </div>

        {activeTab !== "chat" && (
          /* key={activeTab} faz a animacao re-disparar a cada troca de aba; sem
             ela o fade rodava so uma vez, na montagem. */
          <div key={activeTab} className="w-full h-full relative z-10 animate-tab-in">
            <Suspense fallback={<TabSkeleton />}>
              {getTabComponent(activeTab)}
            </Suspense>
          </div>
        )}
      </div>
    </div>
  );
}
