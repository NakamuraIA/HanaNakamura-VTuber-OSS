import { useState, useEffect } from "react";
import { Paintbrush, Save, CheckCircle2, Palette, Accessibility } from "lucide-react";
import { TabHeader } from "../components/shared/TabHeader";
import { Card } from "../components/shared/Card";
import { Button } from "../components/shared/Button";
import {
  ACCESSIBILITY_FONTS,
  AccessibilityConfig,
  applyAccessibility,
  loadAccessibility,
  saveAccessibility,
} from "../../accessibility";

const PRESET_COLORS = [
  { name: "🌸 Rosa Floral", hex: "#f472b6" },
  { name: "💜 Roxo Neon", hex: "#a855f7" },
  { name: "💙 Azul Cyberpunk", hex: "#3b82f6" },
  { name: "💚 Verde Matrix", hex: "#4ade80" },
  { name: "🧡 Laranja Sunset", hex: "#fb923c" },
  { name: "❤️ Vermelho Rubi", hex: "#f43f5e" },
  { name: "✨ Dourado", hex: "#fbbf24" },
  { name: "🩵 Ciano", hex: "#22d3ee" },
];

// Background tone presets (the "make it grayer / darker" control). Values are RGB
// triplets fed into --bg-darkest-rgb and a derived --bg-sidebar.
const BG_TONES = [
  { name: "Preto", rgb: "6, 6, 9" },
  { name: "Grafite", rgb: "15, 16, 20" },
  { name: "Cinza escuro", rgb: "22, 24, 30" },
  { name: "Cinza", rgb: "31, 34, 42" },
];
const DEFAULT_BG_TONE = "6, 6, 9";

function applyBgToneToTheme(rgb: string) {
  document.documentElement.style.setProperty("--bg-darkest-rgb", rgb);
  // Panels sit slightly above the base tone for readable layering.
  document.documentElement.style.setProperty("--bg-sidebar", `rgba(${rgb}, 0.72)`);
}

export function TabPersonalizacao() {
  const [accentColor, setAccentColor] = useState("#a855f7"); // Default Roxo Neon
  const [customHex, setCustomHex] = useState("#a855f7");
  const [opacity, setOpacity] = useState(1.0);
  const [bgTone, setBgTone] = useState(DEFAULT_BG_TONE);
  const [acc, setAcc] = useState<AccessibilityConfig>(() => loadAccessibility());

  const updateAcc = (patch: Partial<AccessibilityConfig>) => {
    setAcc((prev) => {
      const next = { ...prev, ...patch };
      applyAccessibility(next);
      saveAccessibility(next);
      return next;
    });
  };

  // O ideal seria carregar isso do Backend na inicialização
  useEffect(() => {
    // Exemplo: ApiController.getThemeConfig().then(...)
    const savedColor = localStorage.getItem("hana_accent_color") || "#a855f7";
    const savedOpacity = parseFloat(localStorage.getItem("hana_bg_opacity") || "1.0");
    const savedTone = localStorage.getItem("hana_bg_tone") || DEFAULT_BG_TONE;
    setAccentColor(savedColor);
    setCustomHex(savedColor);
    setOpacity(savedOpacity);
    setBgTone(savedTone);
    applyColorToTheme(savedColor);
    applyOpacityToTheme(savedOpacity);
    applyBgToneToTheme(savedTone);
  }, []);

  const handleBgToneSelect = (rgb: string) => {
    setBgTone(rgb);
    applyBgToneToTheme(rgb);
    localStorage.setItem("hana_bg_tone", rgb);
  };

  const applyColorToTheme = (hex: string) => {
    // Aplica a cor de acento como CSS Variable no :root
    document.documentElement.style.setProperty('--purple-neon', hex);
    // Cria um brilho mais suave para a cor glow baseada na cor de acento
    document.documentElement.style.setProperty('--purple-glow', hex);
    document.documentElement.style.setProperty('--purple-dark', `${hex}20`); // Hex + alpha
  };

  const applyOpacityToTheme = (val: number) => {
    document.documentElement.style.setProperty('--bg-opacity', val.toString());
  };

  const handleColorSelect = (hex: string) => {
    setAccentColor(hex);
    setCustomHex(hex);
    applyColorToTheme(hex);
    localStorage.setItem("hana_accent_color", hex); // Salva na hora
  };

  const handleOpacityChange = (val: number) => {
    setOpacity(val);
    applyOpacityToTheme(val);
    localStorage.setItem("hana_bg_opacity", val.toString()); // Salva na hora
  };

  const handleSave = () => {
    // Salva explicitamente (e enviaria ao backend via Tauri)
    localStorage.setItem("hana_accent_color", accentColor);
    localStorage.setItem("hana_bg_opacity", opacity.toString());
    localStorage.setItem("hana_bg_tone", bgTone);
    
    // Aqui chamariamos o ApiController.updateThemeConfig(accentColor)
    // ApiController.updateConfig({ GUI: { accent_color: accentColor } })

    const alertBox = document.getElementById("save-alert");
    if (alertBox) {
      alertBox.classList.remove("opacity-0", "translate-y-4");
      alertBox.classList.add("opacity-100", "translate-y-0");
      setTimeout(() => {
        alertBox.classList.remove("opacity-100", "translate-y-0");
        alertBox.classList.add("opacity-0", "translate-y-4");
      }, 3000);
    }
  };

  return (
    <div className="w-full h-full bg-[var(--bg-sidebar)] backdrop-blur-2xl p-8 overflow-y-auto custom-scrollbar shadow-2xl relative transition-all duration-300">
      {/* HEADER */}
      <TabHeader
        icon={<Paintbrush size={24} />}
        title="Personalização"
        subtitle="Cores de acento, tema visual e identidade da Hana"
      />

      <div className="grid grid-cols-1 md:grid-cols-[1.2fr_1fr] gap-6">
        
        {/* CARD: PALETA DE CORES */}
        <Card className="flex flex-col">
          <div className="absolute top-[-50px] right-[-50px] w-40 h-40 rounded-full blur-[80px] opacity-20 pointer-events-none transition-all duration-500" style={{ backgroundColor: accentColor }}></div>
          
          <h3 className="font-bold text-[var(--text-primary)] mb-6 text-lg flex items-center gap-2">
            <Palette size={20} style={{ color: accentColor }} className="transition-colors duration-500" /> Cores do Sistema
          </h3>
          
          <div className="grid grid-cols-4 gap-4 mb-8">
            {PRESET_COLORS.map((preset) => (
              <button
                key={preset.name}
                onClick={() => handleColorSelect(preset.hex)}
                className="group flex flex-col items-center gap-2"
              >
                <div 
                  className={`w-14 h-14 rounded-full border-2 transition-all duration-300 shadow-lg ${accentColor === preset.hex ? 'scale-110 border-white shadow-[0_0_15px_currentColor]' : 'border-transparent hover:scale-105'}`}
                  style={{ backgroundColor: preset.hex, color: preset.hex }}
                ></div>
                <span className="text-[10px] text-center text-[var(--text-secondary)] font-medium opacity-80 group-hover:opacity-100">{preset.name.split(" ")[1]}</span>
              </button>
            ))}
          </div>

          <div className="bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.05)] rounded-xl p-4 mb-6">
            <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-3 block">Tom do Fundo</span>
            <div className="grid grid-cols-4 gap-2 mb-6">
              {BG_TONES.map((tone) => (
                <button
                  key={tone.rgb}
                  onClick={() => handleBgToneSelect(tone.rgb)}
                  className={`flex flex-col items-center gap-1.5 rounded-lg border p-2 transition-all ${
                    bgTone === tone.rgb ? "border-white/70 scale-[1.03]" : "border-white/10 hover:border-white/30"
                  }`}
                >
                  <span className="h-8 w-full rounded-md border border-white/10" style={{ backgroundColor: `rgb(${tone.rgb})` }} />
                  <span className="text-[10px] text-[var(--text-secondary)] font-medium">{tone.name}</span>
                </button>
              ))}
            </div>

            <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2 block">Transparência do Fundo</span>
            <div className="flex items-center gap-4 mb-6">
              <input 
                type="range" min="0.1" max="1" step="0.05"
                className="w-full h-2 bg-[rgba(0,0,0,0.5)] rounded-lg appearance-none cursor-pointer"
                style={{ accentColor: accentColor }}
                value={opacity}
                onChange={(e) => handleOpacityChange(parseFloat(e.target.value))}
              />
              <span className="text-sm font-bold font-mono text-white bg-[rgba(255,255,255,0.1)] px-3 py-1 rounded-lg">
                {Math.round(opacity * 100)}%
              </span>
            </div>

            <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2 block">Cor Customizada (HEX)</span>
            <div className="flex gap-3">
              <input 
                type="text" 
                value={customHex}
                onChange={(e) => setCustomHex(e.target.value)}
                className="flex-1 bg-[rgba(0,0,0,0.5)] border border-[var(--border-strong)] text-[var(--text-primary)] rounded-lg p-2.5 outline-none font-mono text-sm focus:ring-2 transition-all"
                style={{ '--tw-ring-color': accentColor } as React.CSSProperties}
              />
              <Button onClick={() => handleColorSelect(customHex)} variant="primary">Aplicar</Button>
            </div>
          </div>

          <div className="mt-auto pt-4 border-t border-[var(--border-strong)] flex items-center justify-between">
            <div 
              className="px-6 py-3 rounded-xl font-bold font-mono text-white transition-all duration-500 shadow-inner"
              style={{ backgroundColor: accentColor }}
            >
              HANA_OS_ACTIVE
            </div>

            <Button onClick={handleSave} variant="secondary" icon={<Save size={16} />}>Salvar Tema</Button>
          </div>
        </Card>

        {/* CARD: FOTO / IDENTIDADE HANA */}
        <div className="bg-[rgba(0,0,0,0.4)] backdrop-blur-md border border-[var(--border-strong)] rounded-2xl overflow-hidden shadow-lg relative flex flex-col items-center group">
          {/* Fundo dinâmico baseado na cor de acento */}
          <div className="absolute inset-0 opacity-20 transition-all duration-1000 group-hover:opacity-40" style={{ background: `linear-gradient(to bottom, transparent, ${accentColor})` }}></div>
          
          {/* Imagem da Hana do disco local */}
          <div className="w-full h-[350px] flex items-center justify-center relative z-10 overflow-hidden">
            <div className="absolute inset-0 bg-[url('/hana_foto_01.png')] bg-cover bg-center bg-no-repeat opacity-40 mix-blend-overlay transition-transform duration-1000 group-hover:scale-110"></div>
            
            <div className="w-48 h-48 rounded-full border-4 border-white/20 overflow-hidden shadow-[0_0_30px_rgba(0,0,0,0.8)] flex flex-col items-center justify-center transition-transform duration-500 group-hover:scale-105 group-hover:border-white/50 relative z-20">
              <img src="/hana_foto_01.png" alt="Hana Identidade" className="w-full h-full object-cover" />
            </div>
          </div>

          <div className="relative z-10 w-full p-6 text-center bg-gradient-to-t from-[rgba(10,10,15,1)] to-transparent mt-[-60px] pt-10 flex-1 flex flex-col justify-end">
            <h2 className="text-3xl font-mono font-extrabold tracking-[0.3em] mb-1 transition-colors duration-500" style={{ color: accentColor }}>H A N A</h2>
            <p className="text-sm text-[var(--text-secondary)] tracking-widest uppercase mb-4">Drowsy Onee-san</p>
            
            <div className="inline-flex items-center gap-2 bg-[rgba(255,255,255,0.05)] border border-[rgba(255,255,255,0.1)] rounded-full px-4 py-1.5 mx-auto">
              <span className="w-2 h-2 rounded-full animate-pulse" style={{ backgroundColor: accentColor }}></span>
              <span className="text-xs font-mono text-[var(--text-muted)]">NEXUS CONNECTED • v1.0</span>
            </div>
          </div>
        </div>

      </div>

      {/* CARD: ACESSIBILIDADE (dislexia / TDAH) */}
      <Card className="mt-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-500 flex items-center justify-center text-emerald-300">
            <Accessibility size={20} />
          </div>
          <div>
            <h3 className="font-bold text-[var(--text-primary)] text-lg">Acessibilidade</h3>
            <p className="text-xs text-[var(--text-muted)]">
              Leitura mais fácil (dislexia) e menos distração (TDAH). Aplica na hora e fica salvo.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-5 mt-5">
          {/* Fonte */}
          <div>
            <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2 block">Fonte de leitura</span>
            <div className="flex flex-wrap gap-2">
              {ACCESSIBILITY_FONTS.map((font) => (
                <button
                  key={font.id}
                  onClick={() => updateAcc({ font: font.id })}
                  className={`px-4 py-2 rounded-lg border text-sm transition-all ${
                    acc.font === font.id
                      ? "border-emerald-400 bg-emerald-500/15 text-emerald-200"
                      : "border-[var(--border-strong)] bg-black/40 text-[var(--text-secondary)] hover:border-white/30"
                  }`}
                  style={{ fontFamily: font.stack }}
                >
                  {font.label}
                </button>
              ))}
            </div>
          </div>

          {/* Tamanho */}
          <div>
            <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2 block">
              Tamanho do texto: <b className="text-[var(--text-secondary)]">{acc.fontScale}%</b>
            </span>
            <input
              type="range" min="85" max="140" step="5"
              className="w-full h-2 bg-[rgba(0,0,0,0.5)] rounded-lg appearance-none cursor-pointer accent-emerald-400"
              value={acc.fontScale}
              onChange={(e) => updateAcc({ fontScale: parseInt(e.target.value) })}
            />
          </div>

          {/* Toggles */}
          {[
            { key: "spacing" as const, label: "Leitura espaçada", hint: "Mais espaço entre letras e linhas — ajuda na dislexia." },
            { key: "reduceMotion" as const, label: "Menos animação", hint: "Desliga animações e partículas do fundo. Menos distração e mais leve no PC." },
            { key: "focusMode" as const, label: "Modo foco", hint: "Esconde brilhos decorativos e deixa só o conteúdo." },
          ].map((item) => (
            <label
              key={item.key}
              className="flex items-start gap-3 bg-black/30 border border-[var(--border-strong)] rounded-xl p-3 cursor-pointer hover:border-white/25 transition-all"
            >
              <input
                type="checkbox"
                checked={acc[item.key]}
                onChange={(e) => updateAcc({ [item.key]: e.target.checked })}
                className="mt-1 accent-emerald-400 w-4 h-4"
              />
              <span>
                <span className="block text-sm font-bold text-[var(--text-primary)]">{item.label}</span>
                <span className="block text-xs text-[var(--text-muted)]">{item.hint}</span>
              </span>
            </label>
          ))}
        </div>
      </Card>

      {/* Alerta de Sucesso Float */}
      <div 
        id="save-alert"
        className="fixed bottom-10 left-1/2 -translate-x-1/2 bg-green-500/20 border border-green-500/50 text-green-400 px-6 py-3 rounded-full font-bold shadow-[0_0_20px_rgba(34,197,94,0.3)] backdrop-blur-md opacity-0 translate-y-4 transition-all duration-300 z-50 flex items-center gap-2 pointer-events-none"
      >
        <CheckCircle2 size={20} /> Tema aplicado com sucesso!
      </div>
    </div>
  );
}
