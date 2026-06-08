import { useEffect, useState } from "react";
import { ApiController } from "../controllers/api";
import { ConnectionsConfig } from "../models/types";
import { useAudioUI } from "./useAudioUI";

export function useConnections() {
  const [config, setConfig] = useState<ConnectionsConfig | null>(null);
  const audio = useAudioUI();

  useEffect(() => {
    ApiController.getConnectionsConfig()
      .then((loaded) => {
        setConfig(loaded);
        if (loaded.stt) {
          void ApiController.startVoiceRuntime().catch(console.error);
        } else {
          void ApiController.configureVoiceRuntime().catch(console.error);
        }
      })
      .catch(console.error);
  }, []);

  const updateConfig = async (newConfig: ConnectionsConfig, changedField?: keyof ConnectionsConfig) => {
    setConfig(newConfig);
    const saved = await ApiController.updateConnectionsConfig(newConfig);
    if (saved && typeof saved === "object") setConfig(saved as ConnectionsConfig);
    if (changedField === "tts" && !newConfig.tts) {
      await ApiController.interruptVoiceRuntime("connections_tts_off").catch(console.error);
    }
    await ApiController.configureVoiceRuntime().catch(console.error);
  };

  const toggleField = (field: keyof ConnectionsConfig) => {
    if (!config) return;
    const newState = !config[field];
    if (newState) audio.playToggleOn();
    else audio.playToggleOff();
    void updateConfig({ ...config, [field]: newState }, field);
  };

  const updateKey = (field: "pttKey" | "stopKey", value: string) => {
    if (!config) return;
    void updateConfig({ ...config, [field]: value }, field);
  };

  const updateField = <K extends keyof ConnectionsConfig>(field: K, value: ConnectionsConfig[K]) => {
    if (!config) return;
    void updateConfig({ ...config, [field]: value }, field);
  };

  return { config, toggleField, updateKey, updateField, audioHover: audio.playHover };
}
