import { ShieldAlert } from "lucide-react";
import { PermissionRequest } from "../../../models/types";

interface PermissionModalProps {
  request: PermissionRequest | null;
  onApprove: (id: string) => void;
  onDeny: (id: string) => void;
}

export function PermissionModal({
  request,
  onApprove,
  onDeny,
}: PermissionModalProps) {
  if (!request) return null;
  const highRisk = request.risk === "high";
  return (
    <div className="absolute inset-0 z-[90] bg-black/80 backdrop-blur-md flex items-center justify-center p-6">
      <div className={`w-full max-w-xl rounded-2xl border ${highRisk ? "border-red-400/40 bg-red-950/35" : "border-amber-300/35 bg-slate-950/90"} shadow-2xl p-5`}>
        <div className="flex items-start gap-4">
          <div className={`w-12 h-12 rounded-xl flex items-center justify-center shrink-0 ${highRisk ? "bg-red-500/20 text-red-200" : "bg-amber-400/15 text-amber-200"}`}>
            <ShieldAlert size={24} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-black uppercase tracking-[0.25em] text-[var(--text-muted)]">
              Permissao do Agent Mode
            </div>
            <h3 className="mt-1 text-lg font-black text-white truncate">{request.tool_name}</h3>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">{request.description || "A Hana quer executar uma tool que precisa da sua aprovacao."}</p>
          </div>
          <div className={`rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest ${highRisk ? "bg-red-500/20 text-red-200" : "bg-amber-400/15 text-amber-200"}`}>
            {request.risk}
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-white/10 bg-black/35 p-3">
          <div className="mb-2 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Args</div>
          <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words text-[11px] text-cyan-100">{request.args_preview}</pre>
        </div>

        <div className="mt-4 flex items-center justify-between gap-3">
          <span className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
            Expira em <span className={request.remaining_seconds <= 8 ? "text-red-300" : "text-amber-200"}>{request.remaining_seconds}s</span>
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => onDeny(request.id)}
              className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-2 text-xs font-black uppercase tracking-widest text-red-200 hover:bg-red-500/20"
            >
              Negar
            </button>
            <button
              onClick={() => onApprove(request.id)}
              className="rounded-xl border border-emerald-300/35 bg-emerald-500/15 px-4 py-2 text-xs font-black uppercase tracking-widest text-emerald-200 hover:bg-emerald-500/25"
            >
              Permitir
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
