// Identidade visual da assistente (nome, subtítulo, avatar) — customizável na
// aba Personalização e usada no chat. Persistida em localStorage, igual ao tema.
// O avatar de upload é reduzido pra 256px via canvas antes de salvar (localStorage
// tem ~5MB; foto de celular crua estouraria).
// Tambem vai pro banco, que e a copia duravel — ver api/aparencia.ts.

import { salvarAparencia } from "./api/aparencia";

export interface HanaIdentity {
  name: string;
  subtitle: string;
  /** URL estática (ex: /hana_perfil.png) ou dataURL de upload. */
  avatar: string;
}

export const DEFAULT_IDENTITY: HanaIdentity = {
  name: "Hana Nakamura",
  subtitle: "Drowsy Onee-san",
  avatar: "/hana_perfil.png",
};

const STORAGE_KEY = "hana_identity";
export const IDENTITY_CHANGED_EVENT = "hana-identity-changed";

export function loadIdentity(): HanaIdentity {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_IDENTITY };
    const parsed = JSON.parse(raw) as Partial<HanaIdentity>;
    return {
      name: (parsed.name || DEFAULT_IDENTITY.name).slice(0, 40),
      subtitle: (parsed.subtitle || DEFAULT_IDENTITY.subtitle).slice(0, 60),
      avatar: parsed.avatar || DEFAULT_IDENTITY.avatar,
    };
  } catch {
    return { ...DEFAULT_IDENTITY };
  }
}

export function saveIdentity(identity: HanaIdentity, sync = true): Promise<boolean> {
  const next = {
    name: (identity.name || DEFAULT_IDENTITY.name).slice(0, 40),
    subtitle: (identity.subtitle || DEFAULT_IDENTITY.subtitle).slice(0, 60),
    avatar: identity.avatar || DEFAULT_IDENTITY.avatar,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  // Avisa componentes já montados (ex: TabChat) sem precisar de reload.
  window.dispatchEvent(new CustomEvent(IDENTITY_CHANGED_EVENT));
  return sync ? salvarAparencia({ identity: next }) : Promise.resolve(true);
}

/** Converte um arquivo de imagem em dataURL quadrado de `size`px (crop central). */
export function fileToAvatarDataUrl(file: File, size = 256): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        URL.revokeObjectURL(url);
        reject(new Error("canvas_unavailable"));
        return;
      }
      const side = Math.min(img.width, img.height);
      ctx.drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, size, size);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("invalid_image"));
    };
    img.src = url;
  });
}
