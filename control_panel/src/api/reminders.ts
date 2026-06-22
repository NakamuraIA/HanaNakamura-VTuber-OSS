import { readJson, backendFetch } from "./core";

export interface Reminder {
  id: string;
  text: string;
  due_at: string;
  repeat: "none" | "daily" | string;
  status: string;
  created_at: string;
}

export interface FiredReminder {
  id: string;
  text: string;
  firedAt: string;
}

export const RemindersApi = {
  /** Lists active reminders for the panel card. */
  getReminders: async (): Promise<Reminder[]> => {
    const data = await readJson<{ ok: boolean; reminders: Reminder[] }>("/api/reminders", { ok: false, reminders: [] });
    return data.reminders || [];
  },

  /** Cancels one reminder by id. */
  cancelReminder: async (id: string): Promise<{ ok: boolean }> => {
    try {
      const res = await backendFetch(`/api/reminders/${encodeURIComponent(id)}/cancel`, { method: "POST" });
      return await res.json();
    } catch {
      return { ok: false };
    }
  },

  /** Recent fired reminders; powers the toast notifications. */
  getFiredReminders: async (): Promise<FiredReminder[]> => {
    const data = await readJson<{ ok: boolean; fired: FiredReminder[] }>("/api/reminders/fired", { ok: false, fired: [] });
    return data.fired || [];
  },
};
