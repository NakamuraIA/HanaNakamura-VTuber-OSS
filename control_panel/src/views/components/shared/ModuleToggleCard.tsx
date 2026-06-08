import type { ReactNode } from "react";

interface ModuleToggleCardProps {
  isActive: boolean;
  title: string;
  description: string;
  icon: ReactNode;
  neonColor: string;
  hasHotkey?: boolean;
  hotkeyValue?: string;
  hotkeysList?: string[];
  onToggle: () => void;
  onUpdateKey?: (value: string) => void;
  onHover?: () => void;
  children?: ReactNode;
}

export function ModuleToggleCard({
  isActive,
  title,
  description,
  icon,
  neonColor,
  hasHotkey,
  hotkeyValue,
  hotkeysList,
  onToggle,
  onUpdateKey,
  onHover,
  children
}: ModuleToggleCardProps) {
  const colorHex = neonColor.startsWith('var') ? neonColor : `var(--${neonColor}-neon)`;

  return (
    <div 
      className={`relative overflow-hidden bg-[rgba(0,0,0,0.4)] backdrop-blur-md border rounded-2xl p-6 transition-all duration-500 hover:shadow-[0_0_20px_rgba(255,255,255,0.05)] group flex flex-col h-full`}
      style={{
        borderColor: isActive ? colorHex : 'var(--border-strong)',
        boxShadow: isActive ? `0 0 30px ${colorHex}20` : 'none'
      }}
    >
      {isActive && (
        <div 
          className="absolute top-[-50px] right-[-50px] w-40 h-40 rounded-full blur-[60px] opacity-20 pointer-events-none transition-all duration-1000"
          style={{ backgroundColor: colorHex }}
        ></div>
      )}

      <div className="flex items-start justify-between gap-4 relative z-10 mb-4">
        <div className="flex items-center gap-4">
          <div 
            className={`w-14 h-14 rounded-xl flex items-center justify-center text-3xl transition-all duration-500 ${!isActive ? 'bg-[rgba(255,255,255,0.02)] text-[var(--text-muted)]' : ''}`}
            style={isActive ? { backgroundColor: `${colorHex}20`, color: colorHex, boxShadow: `0 0 20px ${colorHex}30`, transform: 'scale(1.05)' } : {}}
          >
            {icon}
          </div>
          <div className="flex flex-col">
            <h3 className={`font-black text-xl tracking-wide uppercase transition-colors duration-500 ${isActive ? 'text-white' : 'text-[var(--text-secondary)]'}`}>
              {title}
            </h3>
            <div className="flex items-center gap-2 mt-1">
              <span className={`w-2 h-2 rounded-full ${isActive ? 'animate-pulse' : 'opacity-50'}`} style={isActive ? { backgroundColor: colorHex, boxShadow: `0 0 10px ${colorHex}` } : { backgroundColor: 'var(--text-muted)' }}></span>
              <span className={`text-[10px] font-bold font-mono tracking-widest uppercase ${isActive ? '' : 'text-[var(--text-muted)]'}`} style={isActive ? { color: colorHex } : {}}>
                {isActive ? 'Modulo ativo' : 'Offline'}
              </span>
            </div>
          </div>
        </div>

        <div className="shrink-0">
          <label 
            className="relative inline-flex items-center cursor-pointer group/switch"
            onMouseEnter={onHover}
          >
            <input 
              type="checkbox" 
              className="sr-only peer" 
              checked={isActive}
              onChange={onToggle}
            />
            <div 
              className={`relative w-16 h-8 bg-black/60 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-8 after:content-[''] after:absolute after:top-[3px] after:left-[3px] after:bg-[var(--text-muted)] peer-checked:after:bg-white after:rounded-full after:h-[24px] after:w-[24px] after:transition-all duration-300 ${!isActive ? 'border border-[var(--border-strong)]' : 'border-transparent'}`}
              style={isActive ? { backgroundColor: `${colorHex}80`, boxShadow: `inset 0 0 15px ${colorHex}` } : {}}
            ></div>
          </label>
        </div>
      </div>
      
      <p className="text-sm text-[var(--text-muted)] leading-relaxed relative z-10 flex-1">
        {description}
      </p>

      {hasHotkey && onUpdateKey && (
        <div className={`mt-5 pt-4 border-t border-white/5 flex items-center justify-between gap-2 relative z-10 transition-all duration-500 ${isActive ? 'opacity-100' : 'opacity-30 pointer-events-none'}`}>
          <span className="text-xs font-bold uppercase tracking-widest text-[var(--text-secondary)]">Atalho (Hotkey)</span>
          <select
            value={hotkeyValue}
            onChange={(e) => onUpdateKey(e.target.value)}
            disabled={!isActive}
            className={`bg-black/60 rounded-xl px-4 py-2 outline-none font-mono text-sm font-bold cursor-pointer disabled:cursor-not-allowed transition-all border shadow-inner`}
            style={isActive ? { borderColor: `${colorHex}50`, color: colorHex } : { borderColor: 'var(--border-strong)', color: 'var(--text-secondary)' }}
          >
            {hotkeysList?.map(k => <option key={k} value={k} className="bg-gray-900">{k}</option>)}
          </select>
        </div>
      )}

      {children && (
        <div className="mt-5 pt-4 border-t border-white/5 relative z-10">
          {children}
        </div>
      )}
    </div>
  );
}
