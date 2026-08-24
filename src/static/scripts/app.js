import Alpine from "./vendor/alpine.esm.min.js";
import { authStore } from "./stores/auth.js";
import { playerStore } from "./stores/player.js";
import { audioDeck } from "./components/audioDeck.js";
import { queueSection } from "./components/queueSection.js";
import { visualizerPopover } from "./components/visualizerPopover.js";

// data
Alpine.store("auth", authStore);
Alpine.store("player", playerStore);
// comps
Alpine.data("audioDeck", audioDeck);
Alpine.data("queueSection", queueSection);
Alpine.data("visualizerPopover", visualizerPopover);

window.Alpine = Alpine;
Alpine.start();
