const audioPlayer = document.getElementById("main-player");
const playButton = document.getElementById("play");
const pauseButton = document.getElementById("pause");
const titleElement = document.getElementById("title");
const artistElement = document.getElementById("artist");
const durationElement = document.getElementById("duration");
const queueList = document.getElementById("queue-list");
const queueEmpty = document.getElementsByClassName("queue-empty")[0];

let currentDuration = 0;
let isPaused = true;
let durationUpdateFunction = null;

/**
 * Convert seconds to formatted time string (MM:SS or HH:MM:SS)
 * @param {number} totalSeconds - Total seconds to convert
 * @returns {string} Formatted time string
 */
function formatDuration(totalSeconds) {
  const seconds = Math.round(totalSeconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.ceil(seconds % 60);

  if (hours === 0) {
    return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
  } else {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${remainingSeconds
      .toString()
      .padStart(2, "0")}`;
  }
}

/**
 * Update the duration display by incrementing current time
 */
function updateDurationDisplay() {
  currentDuration += 1;
  durationElement.innerText = formatDuration(currentDuration);
}

/**
 * Handle song change events from server
 * @param {Event} event - Server-sent event containing song data
 */
function handleSongChangeEvent(event) {
  try {
    if (queueList.children.length > 1) {
      queueList.removeChild(queueList.children[1]);
      if (queueList.children.length === 1) {
        queueEmpty.classList.remove("hidden");
      }
    }

    const songData = JSON.parse(event.data);

    titleElement.innerText = songData.title || "Unknown Title";
    document.title = songData.title || "PyLive";
    titleElement.href = songData.webpage_url || "#";

    artistElement.innerText = songData.channel || "Unknown Artist";
    artistElement.href = songData.channel_url || "#";

    console.log("Song changed:", songData.title);
  } catch (error) {
    console.error("Error handling song change event:", error);
  }
}

/**
 * Handle queue addition events from server
 * @param {Event} event - Server-sent event containing queue item data
 */
function handleQueueAddEvent(event) {
  try {
    const queueData = JSON.parse(event.data);
    queueEmpty.classList.add("hidden");

    const queueItem = document.createElement("div");
    queueItem.innerHTML = `
      <a href="${queueData.webpage_url || "#"}" class="text" id="title">${
      queueData.title || "Unknown Title"
    }</a>
      <a href="${queueData.channel_url || "#"}" class="text" id="artist">${
      queueData.channel || "Unknown Artist"
    }</a>
    `;

    queueList.appendChild(queueItem);
    console.log("Track added to queue:", queueData.title);
  } catch (error) {
    console.error("Error handling queue add event:", error);
  }
}

/**
 * Start duration tracking when playback begins
 * @returns {Function} Function to stop duration tracking
 */
function startDurationTracking() {
  isPaused = false;
  currentDuration = 0;

  const intervalId = setInterval(() => {
    if (!isPaused) {
      updateDurationDisplay();
    }
  }, 1000);

  return function stopTracking() {
    isPaused = true;
    clearInterval(intervalId);
  };
}

/**
 * Send vote skip request to server
 */
function requestSkip() {
  fetch("/skip", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      if (data.msg === "success") {
        console.log("Skip request successful");
      } else if (data.error === true) {
        throw new Error(data.msg || "Skip request failed");
      }
    })
    .catch((error) => {
      console.error("Error requesting skip:", error);
    });
}

/**
 * Add a track to the queue
 * @param {string} url - URL of the track to add
 */
function addToQueue(url) {
  if (!url || !url.trim()) {
    return;
  }

  fetch("/add", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      url: url.trim(),
    }),
  })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      if (data.msg === "success") {
        console.log("Track added to queue successfully");
      } else if (data.error === true) {
        throw new Error(data.msg || "Failed to add track");
      }
    })
    .catch((error) => {
      console.error("Error adding track to queue:", error);
    });
}

/**
 * Toggle the add queue input box and handle submissions
 */
function toggleAddQueueBox() {
  const addButton = document.getElementById("add-btn");
  const inputBox = document.getElementById("add-queue-box");

  if (addButton.classList.contains("add-btn_Animate")) {
    addButton.classList.remove("add-btn_Animate");
    inputBox.classList.remove("add-queue-box_Animate");

    const url = inputBox.value.trim();
    if (url) {
      addToQueue(url);
      inputBox.value = "";
    }
  } else {
    addButton.classList.add("add-btn_Animate");
    inputBox.classList.add("add-queue-box_Animate");
    setTimeout(() => inputBox.focus(), 100);
  }
}

/**
 * Toggle visualizer settings panel
 */
function toggleVisualizerSettings() {
  const settingsPanel = document.getElementById("visualizer-setting");
  const classList = settingsPanel.classList;

  classList.toggle("hidden");
  classList.toggle("active");
}

document.getElementById("add-queue-box").addEventListener("keyup", (event) => {
  if (event.key === "Enter") {
    toggleAddQueueBox();
  }
});

playButton.addEventListener("click", function () {
  playButton.classList.add("hidden");
  pauseButton.classList.remove("hidden");

  audioPlayer.src = "/stream";
  audioPlayer.play().catch((error) => {
    console.error("Error starting audio playback:", error);
  });

  if (window.ctxAudio && window.ctxAudio.resume) {
    window.ctxAudio.resume().catch((error) => {
      console.warn("Could not resume audio context:", error);
    });
  }

  durationUpdateFunction = startDurationTracking();
});

pauseButton.addEventListener("click", function () {
  playButton.classList.remove("hidden");
  pauseButton.classList.add("hidden");

  audioPlayer.src = "";
  audioPlayer.pause();

  if (durationUpdateFunction) {
    durationUpdateFunction();
    durationUpdateFunction = null;
  }
});

try {
  const eventSource = new EventSource("/watch_event");

  eventSource.addEventListener("nowplaying", handleSongChangeEvent);
  eventSource.addEventListener("queueadd", handleQueueAddEvent);

  eventSource.addEventListener("error", function (error) {
    console.error("EventSource error:", error);
  });

  console.log("Connected to server events");
} catch (error) {
  console.error("Failed to connect to server events:", error);
}

window.voteSkip = requestSkip;
window.AddQueueBox = toggleAddQueueBox;
window.toggleSettings = toggleVisualizerSettings;
