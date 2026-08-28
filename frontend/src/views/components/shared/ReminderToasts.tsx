import { useEffect, useRef, useState } from "react";
import { BellRing, X } from "lucide-react";
import { ApiController } from "../../../controllers/api";
import type { FiredReminder } from "../../../api/reminders";

const POLL_MS = 15000;
const TOAST_MS = 12000;
const LAST_SEEN_KEY = "hana_reminder_last_seen";

/**
 * Global toast stack for fired reminders. Polls the backend fired-log and shows
 * a dismissible notification for entries newer than the last one seen.
 */
export function ReminderToasts() {
  const [toasts, setToasts] = useState<FiredReminder[]>([]);
  const lastSeenRef = useRef<string>(localStorage.getItem(LAST_SEEN_KEY) || "");

  useEffect(() => {
    let alive = true;

    const poll = async () => {
      const fired = await ApiController.getFiredReminders();
      if (!alive || fired.length === 0) return;
      const lastSeen = lastSeenRef.current;
      const fresh = lastSeen ? fired.filter((item) => item.firedAt > lastSeen) : [];
      const newest = fired[fired.length - 1]?.firedAt || "";
      if (newest && newest !== lastSeen) {
        lastSeenRef.current = newest;
        localStorage.setItem(LAST_SEEN_KEY, newest);
      }
      if (fresh.length > 0) {
        setToasts((current) => [...current, ...fresh].slice(-4));
        for (const item of fresh) {
          window.setTimeout(() => {
            setToasts((current) => current.filter((toast) => toast !== item));
          }, TOAST_MS);
        }
      }
    };

    // First poll only records the baseline (no replay of old reminders on load).
    ApiController.getFiredReminders().then((fired) => {
      const newest = fired[fired.length - 1]?.firedAt || "";
      if (!lastSeenRef.current && newest) {
        lastSeenRef.current = newest;
        localStorage.setItem(LAST_SEEN_KEY, newest);
      }
    });
    const timer = window.setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-3">
      {toasts.map((toast, index) => (
        <div
          key={`${toast.id}-${toast.firedAt}-${index}`}
          className="flex items-start gap-3 rounded-xl border border-[var(--accent)]/40 bg-black/85 px-4 py-3 shadow-[0_8px_30px_rgba(0,0,0,0.5)] backdrop-blur-xl max-w-sm"
        >
          <BellRing size={18} className="mt-0.5 shrink-0 text-[var(--accent)]" />
          <div className="min-w-0">
            <p className="text-xs font-mono uppercase tracking-widest text-[var(--text-muted)]">Lembrete</p>
            <p className="mt-0.5 break-words text-sm text-white">{toast.text}</p>
          </div>
          <button
            type="button"
            onClick={() => setToasts((current) => current.filter((item) => item !== toast))}
            className="ml-auto shrink-0 rounded p-1 text-[var(--text-muted)] transition-colors hover:text-white"
            aria-label="Fechar lembrete"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
