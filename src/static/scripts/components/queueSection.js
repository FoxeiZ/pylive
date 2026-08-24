import Alpine from "../vendor/alpine.esm.min.js";

export function queueSection() {
  return {
    get player() {
      return Alpine.store("player");
    },
  };
}
