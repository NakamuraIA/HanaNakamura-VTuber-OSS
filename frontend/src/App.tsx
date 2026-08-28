import { useEffect } from "react";
import "./App.css";
import { MainLayout } from "./views/layouts/MainLayout";
import { applyAccessibility, loadAccessibility, saveAccessibility } from "./accessibility";
import { applyTheme, loadTheme, saveTheme } from "./theme";
import { loadIdentity, saveIdentity } from "./identity";
import { sincronizarAparencia } from "./api/aparencia";

function App() {
  useEffect(() => {
    // 1) Pinta JA, com o que esta no localStorage. Sincrono de proposito:
    //    esperar a rede aqui deixaria a tela branca em toda abertura.
    const theme = loadTheme();
    const identity = loadIdentity();
    const accessibility = loadAccessibility();
    applyTheme(theme);
    applyAccessibility(accessibility);

    // 2) O banco vence onde ja existe valor. Campos antigos que ainda faltam
    //    nele recebem a copia local uma unica vez.
    void sincronizarAparencia({ theme, identity, accessibility }).then((ui) => {
      if (!ui) return;
      if (ui.theme && typeof ui.theme === "object") void saveTheme(ui.theme as typeof theme, false);
      if (ui.identity && typeof ui.identity === "object") void saveIdentity(ui.identity as typeof identity, false);
      if (ui.accessibility && typeof ui.accessibility === "object") {
        void saveAccessibility(ui.accessibility as typeof accessibility, false);
      }
      applyTheme(loadTheme());
      applyAccessibility(loadAccessibility());
    });
  }, []);

  return <MainLayout />;
}

export default App;
