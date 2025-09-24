import Oscilloscope from "./dist/oscilloscope.js";

const AudioContextClass = window.AudioContext || window.webkitAudioContext;

try {
  window.ctxAudio = new AudioContextClass();
  console.log("Audio context initialized successfully");
} catch (error) {
  console.error("Failed to initialize audio context:", error);
  window.ctxAudio = null;
}

const audioElement = document.getElementById("main-player");
if (!audioElement) {
  console.error("Audio player element not found");
}

let audioSource = null;
if (window.ctxAudio && audioElement) {
  try {
    audioSource = window.ctxAudio.createMediaElementSource(audioElement);
    console.log("Audio source created successfully");
  } catch (error) {
    console.error("Failed to create audio source:", error);
  }
}

const visualizerOptions = {
  stroke: 1, // Line thickness for waveform
  type: "bars", // Visualization type (bars or oscilloscope)
  fftSize: 2048, // FFT size (must be power of 2, 32-32768)
  minDecibels: -62, // Minimum volume threshold
};

const visualizerCanvas = document.getElementById("visualizer");
if (!visualizerCanvas) {
  console.error("Visualizer canvas element not found");
}

let canvasContext = null;
if (visualizerCanvas) {
  try {
    canvasContext = visualizerCanvas.getContext("2d");
    console.log("Canvas context obtained successfully");
  } catch (error) {
    console.error("Failed to get canvas context:", error);
  }
}

if (audioSource && canvasContext && window.ctxAudio) {
  try {
    window.visualizer = new Oscilloscope(
      audioSource,
      canvasContext,
      window.ctxAudio,
      visualizerOptions
    );
    console.log("Visualizer initialized successfully");
  } catch (error) {
    console.error("Failed to initialize visualizer:", error);
    window.visualizer = null;
  }
} else {
  console.error("Visualizer not initialized due to missing components");
  window.visualizer = null;
}
