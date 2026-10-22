import { create } from 'zustand';
import { createJSONStorage, persist, type StateStorage } from 'zustand/middleware';

/** UI-only state. Business data never lives here — it comes from the API via React Query. */

const safeStorage: StateStorage = {
  getItem: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  setItem: (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
  removeItem: (k) => { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};

export interface Toast { id: number; text: string; tone: 'ok' | 'info' | 'warn' | 'error' }
interface ConfirmState { title: string; message: string; confirmLabel: string; danger?: boolean; onConfirm: () => void }

interface Ui {
  theme: 'dark' | 'light';
  setTheme: (t: 'dark' | 'light') => void;
  sidebarOpen: boolean;
  setSidebar: (v: boolean) => void;
  toasts: Toast[];
  toast: (text: string, tone?: Toast['tone']) => void;
  dropToast: (id: number) => void;
  confirm: ConfirmState | null;
  ask: (c: ConfirmState) => void;
  closeConfirm: () => void;
}

let nextToast = 1;

export const useUi = create<Ui>()(
  persist(
    (set, get) => ({
      theme: 'light',
      setTheme: (theme) => set({ theme }),
      sidebarOpen: false,
      setSidebar: (v) => set({ sidebarOpen: v }),
      toasts: [],
      toast: (text, tone = 'ok') => {
        const id = nextToast++;
        set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, tone }] }));
        setTimeout(() => get().dropToast(id), tone === 'error' ? 6000 : 3500);
      },
      dropToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
      confirm: null,
      ask: (c) => set({ confirm: c }),
      closeConfirm: () => set({ confirm: null }),
    }),
    { name: 'codencode-sales-ui-v1', storage: createJSONStorage(() => safeStorage), partialize: (s) => ({ theme: s.theme }) },
  ),
);
