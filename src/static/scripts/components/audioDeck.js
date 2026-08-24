import Alpine from "../vendor/alpine.esm.min.js";

export function audioDeck() {
  return {
    get player() {
      return Alpine.store("player");
    },
  };
}
