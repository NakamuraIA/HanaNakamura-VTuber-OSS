import { useEffect, useState } from "react";
import { Sidebar } from "./Sidebar";
import { MenuOption } from "../../models/types";

// Importando Ícones do Lucide
import {
  MonitorDot, BrainCircuit, Database, MessageSquareText,
  Cable, Paintbrush, ScrollText, Network, TerminalSquare
} from "lucide-react";

// Importando as Páginas (Views)
import { TabGeral } from "../pages/TabGeral";
import { TabLLM } from "../pages/TabLLM";
import { TabPersonalizacao } from "../pages/TabPersonalizacao";
import { TabChat } from "../pages/TabChat";
import { TabConexoes } from "../pages/TabConexoes";
import { TabMemoria } from "../pages/TabMemoria";
import { TabLogs } from "../pages/TabLogs";
import { TabMCP } from "../pages/TabMCP";
import { TabTerminalAgent } from "../pages/TabTerminalAgent";
import { CyberBackground } from "../components/CyberBackground";
import { ReminderToasts } from "../components/shared/ReminderToasts";

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

export function MainLayout() {
  const [activeTab, setActiveTab] = useState("geral");

  const isImplemented = ["geral", "llm", "personalizacao", "chat", "terminal-agente", "conexoes", "mcp", "memoria", "logs"].includes(activeTab);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ tab?: string }>).detail;
      if (detail?.tab) {
        setActiveTab(detail.tab);
      }
    };
    window.addEventListener("hana:navigate-tab", handler);
    return () => window.removeEventListener("hana:navigate-tab", handler);
  }, []);

  return (
    <div className="flex h-screen w-full text-[var(--text-primary)] bg-transparent">
      <CyberBackground />
      <ReminderToasts />
      <Sidebar menus={menus} activeTab={activeTab} onTabChange={setActiveTab} />
      
      {/* Main Content com Efeito de Vidro */}
      <div className="flex-1 h-full overflow-hidden relative p-0">
        {/* Luzes de fundo atmosféricas (bem sutis, sem ofuscar). */}
        <div className="absolute top-[-10%] right-[-5%] w-[500px] h-[500px] bg-slate-500 rounded-full blur-[160px] opacity-[0.03] pointer-events-none"></div>
        <div className="absolute bottom-[-10%] left-[20%] w-[400px] h-[400px] bg-slate-500 rounded-full blur-[160px] opacity-[0.03] pointer-events-none"></div>
        
        <div className="w-full h-full relative z-10 animate-fade-in">
          
          <div className={activeTab === "geral" ? "block w-full h-full" : "hidden"}>
            <TabGeral />
          </div>
          
          <div className={activeTab === "llm" ? "block w-full h-full" : "hidden"}>
            <TabLLM />
          </div>
          
          <div className={activeTab === "personalizacao" ? "block w-full h-full" : "hidden"}>
            <TabPersonalizacao />
          </div>

          <div className={activeTab === "chat" ? "block w-full h-full" : "hidden"}>
            <TabChat isActive={activeTab === "chat"} />
          </div>

          <div className={activeTab === "terminal-agente" ? "block w-full h-full" : "hidden"}>
            <TabTerminalAgent isActive={activeTab === "terminal-agente"} />
          </div>

          <div className={activeTab === "conexoes" ? "block w-full h-full" : "hidden"}>
            <TabConexoes />
          </div>

          <div className={activeTab === "mcp" ? "block w-full h-full" : "hidden"}>
            <TabMCP />
          </div>

          <div className={activeTab === "memoria" ? "block w-full h-full" : "hidden"}>
            <TabMemoria />
          </div>

          <div className={activeTab === "logs" ? "block w-full h-full" : "hidden"}>
            <TabLogs />
          </div>

          {!isImplemented && (
            <div className="w-full h-full bg-[rgba(15,15,20,0.5)] backdrop-blur-2xl border border-[var(--border-strong)] rounded-2xl p-8 overflow-y-auto">
              <h2 className="text-3xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-[var(--purple-neon)] to-[var(--cyan-neon)] mb-2">
                {menus.find(m => m.id === activeTab)?.label}
              </h2>
              <p className="text-[var(--text-secondary)]">
                (Work in Progress - MVC Estruturado)
              </p>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
