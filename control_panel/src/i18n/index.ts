import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enCommon from "./locales/en/common.json";
import ptBRCommon from "./locales/pt-BR/common.json";

void i18n.use(initReactI18next).init({
  fallbackLng: "en",
  supportedLngs: ["en", "pt-BR", "es", "ja", "ko", "zh-CN", "fr", "de"],
  ns: ["common", "chat", "projects", "agent"],
  defaultNS: "common",
  interpolation: {
    escapeValue: false,
  },
  resources: {
    en: {
      common: enCommon,
      chat: {},
      projects: {},
      agent: {},
    },
    "pt-BR": {
      common: ptBRCommon,
      chat: {},
      projects: {},
      agent: {},
    },
  },
});

export default i18n;
