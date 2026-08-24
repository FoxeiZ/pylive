import Alpine from "../vendor/alpine.esm.min.js";

export function visualizerPopover() {
  return {
    get player() {
      return Alpine.store("player");
    },
    modes: [
      { id: "bars", label: "Bars" },
      { id: "waveform", label: "Waveform" },
      { id: "symmetric", label: "Symmetric" },
      { id: "round_bars", label: "Pill Bars" },
    ],
    themes: [
      { id: "cyan", label: "Cyan", color: "#06b6d4" },
      { id: "emerald", label: "Emerald", color: "#10b981" },
      { id: "violet", label: "Violet", color: "#8b5cf6" },
      { id: "amber", label: "Amber", color: "#f59e0b" },
      { id: "coral", label: "Coral", color: "#f43f5e" },
      { id: "monochrome", label: "Mono", color: "#f1f5f9" },
    ],
  };
}
