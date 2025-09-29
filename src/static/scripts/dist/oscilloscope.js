export default class Oscilloscope {
  static VISUALIZATION_TYPES = {
    BARS: "bars",
    OSCILLOSCOPE: "oscilloscope",
  };

  static DEFAULTS = {
    FFT_SIZE: 1024,
    SENSITIVITY: 0.6,
    MIN_DECIBELS: -100,
    MAX_DECIBELS: -30,
    COLOR: "black",
    MAX_FPS: 48,
    MULTIPLIER: 1,
    THICKNESS: 1,
    X_OFFSET: 0,
    Y_OFFSET: 0,
    VISUALIZATION_TYPE: "bars",
  };

  /**
   * Create an Oscilloscope instance
   *
   * @param {AudioNode} source - Web Audio API source node
   * @param {CanvasRenderingContext2D} canvasContext - Canvas 2D rendering context
   * @param {AudioContext} audioContext - Web Audio API context
   * @param {Object} options - Configuration options
   * @param {number} [options.fftSize=1024] - FFT size for frequency analysis
   * @param {number} [options.sensitivity=0.6] - Audio sensitivity (0-1)
   * @param {number} [options.minDecibels=-100] - Minimum decibel threshold
   * @param {number} [options.maxDecibels=-30] - Maximum decibel threshold
   * @param {string} [options.color='black'] - Visualization color
   * @param {number} [options.maxFPS=48] - Maximum frames per second
   * @param {number} [options.multiplier=1] - Amplitude multiplier
   * @param {string} [options.type='bars'] - Visualization type ('bars' or 'oscilloscope')
   * @param {number} [options.stroke=1] - Line/bar thickness
   * @param {number} [options.XOffset=0] - Horizontal offset
   * @param {number} [options.YOffset=0] - Vertical offset
   * @throws {Error} When source is not an AudioNode
   * @throws {Error} When required parameters are missing or invalid
   */
  constructor(source, canvasContext, audioContext, options = {}) {
    try {
      this._validateConstructorParameters(source, canvasContext, audioContext);
      this._initializeAudioComponents(source, audioContext);
      this._initializeConfiguration(options);
      this._initializeVisualization(canvasContext);

      console.log("Oscilloscope initialized successfully");
    } catch (error) {
      console.error("Failed to initialize Oscilloscope:", error);
      throw error;
    }
  }

  /**
   * Validate constructor parameters
   * @private
   */
  _validateConstructorParameters(source, canvasContext, audioContext) {
    if (!(source instanceof window.AudioNode)) {
      throw new Error("Oscilloscope source must be an AudioNode");
    }

    if (!canvasContext || typeof canvasContext.clearRect !== "function") {
      throw new Error("Invalid canvas context provided");
    }

    if (!audioContext || !audioContext.destination) {
      throw new Error("Invalid audio context provided");
    }
  }

  /**
   * Initialize audio components
   * @private
   */
  _initializeAudioComponents(source, audioContext) {
    if (source instanceof window.AnalyserNode) {
      this.analyser = source;
    } else {
      this.analyser = source.context.createAnalyser();
      source.connect(this.analyser);
    }

    source.connect(audioContext.destination);

    this.audioContext = audioContext;
    this.sourceNode = source;
  }

  /**
   * Initialize configuration with options
   * @private
   */
  _initializeConfiguration(options) {
    this.analyser.fftSize = this._validateFFTSize(
      options.fftSize || Oscilloscope.DEFAULTS.FFT_SIZE
    );
    this.analyser.smoothingTimeConstant = this._clamp(
      options.sensitivity || Oscilloscope.DEFAULTS.SENSITIVITY,
      0,
      1
    );
    this.analyser.minDecibels =
      options.minDecibels || Oscilloscope.DEFAULTS.MIN_DECIBELS;
    this.analyser.maxDecibels =
      options.maxDecibels || Oscilloscope.DEFAULTS.MAX_DECIBELS;

    this.color = options.color || Oscilloscope.DEFAULTS.COLOR;
    this.maxFPS = Math.max(1, options.maxFPS || Oscilloscope.DEFAULTS.MAX_FPS);
    this.multiplier = Math.max(
      0.1,
      options.multiplier || Oscilloscope.DEFAULTS.MULTIPLIER
    );
    this.type = this._validateVisualizationType(
      options.type || Oscilloscope.DEFAULTS.VISUALIZATION_TYPE
    );
    this.thickness = Math.max(
      0.1,
      options.stroke || Oscilloscope.DEFAULTS.THICKNESS
    );
    this.xOffset = options.XOffset || Oscilloscope.DEFAULTS.X_OFFSET;
    this.yOffset = options.YOffset || Oscilloscope.DEFAULTS.Y_OFFSET;
  }

  /**
   * Initialize visualization components
   * @private
   */
  _initializeVisualization(canvasContext) {
    this.canvasContext = canvasContext;
    this.isAnimating = false;
    this.animationId = null;
    this.targetFrameTime = 1000 / this.maxFPS;

    // pre-allocate arrays for better performance
    this._frequencyData = null;
    this._timeData = null;
    this._frequencyMultipliers = null;

    this.visualizationMethods = {
      [Oscilloscope.VISUALIZATION_TYPES.BARS]:
        this._drawFrequencyBars.bind(this),
      [Oscilloscope.VISUALIZATION_TYPES.OSCILLOSCOPE]:
        this._drawOscilloscope.bind(this),
    };
  }

  /**
   * Validate FFT size (must be power of 2)
   * @private
   */
  _validateFFTSize(size) {
    const validSizes = [
      32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768,
    ];
    if (!validSizes.includes(size)) {
      return 1024;
    }
    return size;
  }

  /**
   * Validate visualization type
   * @private
   */
  _validateVisualizationType(type) {
    const validTypes = Object.values(Oscilloscope.VISUALIZATION_TYPES);
    if (!validTypes.includes(type)) {
      return Oscilloscope.VISUALIZATION_TYPES.BARS;
    }
    return type;
  }

  /**
   * Clamp value between min and max
   * @private
   */
  _clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  /**
   * Start the visualization animation
   *
   * @param {number} [x=0] - X coordinate offset
   * @param {number} [y=0] - Y coordinate offset
   * @param {number} [width] - Visualization width (defaults to canvas width)
   * @param {number} [height] - Visualization height (defaults to canvas height)
   * @throws {Error} When animation is already running
   */
  startAnimation(x = 0, y = 0, width = null, height = null) {
    if (this.isAnimating) {
      throw new Error("Oscilloscope animation is already running");
    }

    try {
      this.isAnimating = true;

      const canvas = this.canvasContext.canvas;
      const drawWidth = width !== null ? width : canvas.width - x;
      const drawHeight = height !== null ? height : canvas.height - y;

      console.log(
        `Starting oscilloscope animation: ${drawWidth}x${drawHeight} at (${x}, ${y})`
      );

      this._startAnimationLoop(x, y, drawWidth, drawHeight);
    } catch (error) {
      this.isAnimating = false;
      console.error("Failed to start animation:", error);
      throw error;
    }
  }

  /**
   * Internal animation loop using requestAnimationFrame
   * @private
   */
  _startAnimationLoop(x, y, width, height) {
    let lastFrameTime = 0;

    const animationLoop = (currentTime) => {
      if (!this.isAnimating) {
        return;
      }

      if (currentTime - lastFrameTime >= this.targetFrameTime) {
        try {
          this._clearCanvas();
          this._renderVisualization(x, y, width, height);
          lastFrameTime = currentTime;
        } catch (error) {
          console.error("Error in animation loop:", error);
          this.stopAnimation();
          return;
        }
      }

      this.animationId = requestAnimationFrame(animationLoop);
    };

    this.animationId = requestAnimationFrame(animationLoop);
  }

  /**
   * Stop the visualization animation
   */
  stopAnimation() {
    if (this.isAnimating) {
      this.isAnimating = false;

      if (this.animationId) {
        cancelAnimationFrame(this.animationId);
        this.animationId = null;
      }

      this._clearCanvas();
      console.log("Oscilloscope animation stopped");
    }
  }

  /**
   * Clear the canvas
   * @private
   */
  _clearCanvas() {
    try {
      const canvas = this.canvasContext.canvas;
      this.canvasContext.clearRect(0, 0, canvas.width, canvas.height);
    } catch (error) {
      console.error("Error clearing canvas:", error);
    }
  }

  /**
   * Render the current visualization
   * @private
   */
  _renderVisualization(x, y, width, height) {
    const visualizationMethod = this.visualizationMethods[this.type];
    if (visualizationMethod) {
      visualizationMethod(this.canvasContext, x, y, width, height);
    } else {
      console.error(`Unknown visualization type: ${this.type}`);
    }
  }

  /**
   * Pre-calculate frequency multipliers for better performance
   * @private
   */
  _precalculateFrequencyMultipliers(bufferLength) {
    if (
      !this._frequencyMultipliers ||
      this._frequencyMultipliers.length !== bufferLength
    ) {
      this._frequencyMultipliers = new Float32Array(bufferLength);
      for (let i = 0; i < bufferLength; i++) {
        const normalizedIndex = i / bufferLength;
        if (normalizedIndex <= 0.1) {
          this._frequencyMultipliers[i] = 1.5;
        } else if (normalizedIndex <= 0.3) {
          this._frequencyMultipliers[i] = 1.8;
        } else if (normalizedIndex <= 0.7) {
          this._frequencyMultipliers[i] = 2.2;
        } else {
          this._frequencyMultipliers[i] = 2.5;
        }
      }
    }
  }

  /**
   * Draw frequency bars visualization (optimized with batch rendering)
   * @private
   */
  _drawFrequencyBars(
    ctx,
    x = 0,
    y = 0,
    width = ctx.canvas.width - x,
    height = ctx.canvas.height - y
  ) {
    try {
      const bufferLength = this.analyser.frequencyBinCount;

      // reuse array if same size, otherwise create new one
      if (!this._frequencyData || this._frequencyData.length !== bufferLength) {
        this._frequencyData = new Uint8Array(bufferLength);
      }

      this.analyser.getByteFrequencyData(this._frequencyData);
      this._precalculateFrequencyMultipliers(bufferLength);

      const barWidth = (width / bufferLength) * this.thickness;
      const heightMultiplier = height * this.multiplier * 0.5;
      const yBase = height + this.yOffset;

      // batch drawing using Path2D for better performance
      ctx.fillStyle = this.color;
      ctx.beginPath();

      let positionX = x;
      for (let i = 0; i < bufferLength; i++) {
        const normalizedValue = this._frequencyData[i] / 255;
        const barHeight =
          normalizedValue * heightMultiplier * this._frequencyMultipliers[i];

        if (barHeight > 0.5) {
          // skip tiny bars for performance
          ctx.rect(positionX, yBase - barHeight, barWidth, barHeight);
        }

        positionX += barWidth + 1;
      }

      ctx.fill();
    } catch (error) {
      console.error("Error drawing frequency bars:", error);
    }
  }

  /**
   * Draw oscilloscope (time domain) visualization (optimized with reduced sampling)
   * @private
   */
  _drawOscilloscope(
    ctx,
    x = 0,
    y = 0,
    width = ctx.canvas.width - x,
    height = ctx.canvas.height - y
  ) {
    try {
      const bufferLength = this.analyser.fftSize;

      // reuse array if same size, otherwise create new one
      if (!this._timeData || this._timeData.length !== bufferLength) {
        this._timeData = new Uint8Array(bufferLength);
      }

      this.analyser.getByteTimeDomainData(this._timeData);

      // adaptive sampling based on canvas width for performance
      const maxPoints = Math.min(bufferLength, width * 2);
      const step = width / maxPoints;
      const sampleStep = Math.max(1, Math.floor(bufferLength / maxPoints));
      const centerY = y + height * 0.5;
      const amplitudeScale = height * this.multiplier * 0.4;

      ctx.beginPath();
      ctx.lineWidth = this.thickness;
      ctx.strokeStyle = this.color;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";

      let firstPoint = true;
      let currentX = x;

      for (let i = 0; i < bufferLength; i += sampleStep) {
        const sample = this._timeData[i];
        const normalizedSample = (sample - 128) / 128;
        const yPos = centerY + normalizedSample * amplitudeScale + this.yOffset;

        if (firstPoint) {
          ctx.moveTo(currentX, yPos);
          firstPoint = false;
        } else {
          ctx.lineTo(currentX, yPos);
        }

        currentX += step;
        if (currentX > x + width) break;
      }

      ctx.stroke();
    } catch (error) {
      console.error("Error drawing oscilloscope:", error);
    }
  }

  setVisualizationType(type) {
    try {
      const newType = this._validateVisualizationType(type.toLowerCase());

      if (newType === this.type) {
        return;
      }

      const wasAnimating = this.isAnimating;
      const previousType = this.type;

      if (wasAnimating) {
        this.stopAnimation();
      }

      this.type = newType;
      console.log(
        `Visualization type changed from ${previousType} to ${newType}`
      );

      if (wasAnimating) {
        this.startAnimation();
      }

      if (previousType === Oscilloscope.VISUALIZATION_TYPES.OSCILLOSCOPE) {
        this.canvasContext.beginPath();
      }
    } catch (error) {
      console.error("Error changing visualization type:", error);
    }
  }

  /**
   * Change the maximum frames per second
   *
   * @param {number} fps - New FPS value (minimum: 1)
   */
  setFrameRate(fps) {
    try {
      const newFPS = Math.max(
        1,
        Math.min(120, Number(fps) || Oscilloscope.DEFAULTS.MAX_FPS)
      );
      this.maxFPS = newFPS;
      this.targetFrameTime = 1000 / newFPS;
      console.log(`Frame rate set to ${newFPS} FPS`);
    } catch (error) {
      console.error("Error setting frame rate:", error);
    }
  }

  /**
   * Change canvas dimensions
   *
   * @param {number} width - New canvas width
   * @param {number} height - New canvas height
   */
  setCanvasSize(width, height) {
    try {
      if (width <= 0 || height <= 0) {
        throw new Error("Canvas dimensions must be positive");
      }

      this.canvasContext.canvas.width = width;
      this.canvasContext.canvas.height = height;

      console.log(`Canvas size set to ${width}x${height}`);
    } catch (error) {
      console.error("Error setting canvas size:", error);
    }
  }

  /**
   * Change line/bar thickness
   *
   * @param {number} thickness - New thickness value (minimum: 0.1)
   */
  setThickness(thickness) {
    try {
      const value =
        thickness === "" ? Oscilloscope.DEFAULTS.THICKNESS : Number(thickness);
      this.thickness = Math.max(0.1, value || Oscilloscope.DEFAULTS.THICKNESS);
      console.log(`Thickness set to ${this.thickness}`);
    } catch (error) {
      console.error("Error setting thickness:", error);
    }
  }

  /**
   * Change visualization color
   *
   * @param {string} color - New color value (CSS color string)
   */
  setColor(color) {
    try {
      this.color = color || Oscilloscope.DEFAULTS.COLOR;
      console.log(`Color set to ${this.color}`);
    } catch (error) {
      console.error("Error setting color:", error);
    }
  }

  /**
   * Change audio sensitivity (smoothing time constant)
   *
   * @param {number} sensitivity - New sensitivity value (0-1)
   */
  setSensitivity(sensitivity) {
    try {
      const value =
        sensitivity === ""
          ? Oscilloscope.DEFAULTS.SENSITIVITY
          : Number(sensitivity);
      const clampedValue = this._clamp(
        value || Oscilloscope.DEFAULTS.SENSITIVITY,
        0,
        1
      );

      this.analyser.smoothingTimeConstant = clampedValue;
      console.log(`Sensitivity set to ${clampedValue}`);
    } catch (error) {
      console.error("Error setting sensitivity:", error);
    }
  }

  /**
   * Change amplitude multiplier
   *
   * @param {number} multiplier - New multiplier value (minimum: 0.1)
   */
  setAmplitudeMultiplier(multiplier) {
    try {
      const value =
        multiplier === ""
          ? Oscilloscope.DEFAULTS.MULTIPLIER
          : Number(multiplier);
      this.multiplier = Math.max(
        0.1,
        value || Oscilloscope.DEFAULTS.MULTIPLIER
      );
      console.log(`Amplitude multiplier set to ${this.multiplier}`);
    } catch (error) {
      console.error("Error setting amplitude multiplier:", error);
    }
  }

  /**
   * Change minimum decibels threshold
   *
   * @param {number} decibels - New minimum decibels value
   */
  setMinDecibels(decibels) {
    try {
      const value =
        decibels === "" ? Oscilloscope.DEFAULTS.MIN_DECIBELS : Number(decibels);
      this.analyser.minDecibels = value || Oscilloscope.DEFAULTS.MIN_DECIBELS;
      console.log(`Minimum decibels set to ${this.analyser.minDecibels}`);
    } catch (error) {
      console.error("Error setting minimum decibels:", error);
    }
  }

  /**
   * Change maximum decibels threshold
   *
   * @param {number} decibels - New maximum decibels value
   */
  setMaxDecibels(decibels) {
    try {
      const value =
        decibels === "" ? Oscilloscope.DEFAULTS.MAX_DECIBELS : Number(decibels);
      this.analyser.maxDecibels = value || Oscilloscope.DEFAULTS.MAX_DECIBELS;
      console.log(`Maximum decibels set to ${this.analyser.maxDecibels}`);
    } catch (error) {
      console.error("Error setting maximum decibels:", error);
    }
  }

  /**
   * Toggle animation on/off
   */
  toggleAnimation() {
    try {
      if (this.isAnimating) {
        this.stopAnimation();
      } else {
        this.startAnimation();
      }
    } catch (error) {
      console.error("Error toggling animation:", error);
    }
  }

  /**
   * Get current configuration
   *
   * @returns {Object} Current oscilloscope configuration
   */
  getConfiguration() {
    return {
      isAnimating: this.isAnimating,
      type: this.type,
      fftSize: this.analyser.fftSize,
      sensitivity: this.analyser.smoothingTimeConstant,
      minDecibels: this.analyser.minDecibels,
      maxDecibels: this.analyser.maxDecibels,
      color: this.color,
      maxFPS: this.maxFPS,
      multiplier: this.multiplier,
      thickness: this.thickness,
      xOffset: this.xOffset,
      yOffset: this.yOffset,
    };
  }

  /**
   * Reset to default configuration
   */
  resetToDefaults() {
    try {
      this.stopAnimation();

      this.analyser.fftSize = Oscilloscope.DEFAULTS.FFT_SIZE;
      this.analyser.smoothingTimeConstant = Oscilloscope.DEFAULTS.SENSITIVITY;
      this.analyser.minDecibels = Oscilloscope.DEFAULTS.MIN_DECIBELS;
      this.analyser.maxDecibels = Oscilloscope.DEFAULTS.MAX_DECIBELS;
      this.color = Oscilloscope.DEFAULTS.COLOR;
      this.maxFPS = Oscilloscope.DEFAULTS.MAX_FPS;
      this.targetFrameTime = 1000 / Oscilloscope.DEFAULTS.MAX_FPS;
      this.multiplier = Oscilloscope.DEFAULTS.MULTIPLIER;
      this.type = Oscilloscope.DEFAULTS.VISUALIZATION_TYPE;
      this.thickness = Oscilloscope.DEFAULTS.THICKNESS;
      this.xOffset = Oscilloscope.DEFAULTS.X_OFFSET;
      this.yOffset = Oscilloscope.DEFAULTS.Y_OFFSET;

      console.log("Oscilloscope reset to default configuration");
    } catch (error) {
      console.error("Error resetting to defaults:", error);
    }
  }

  /**
   * Cleanup and destroy the oscilloscope instance
   */
  destroy() {
    try {
      this.stopAnimation();

      if (this.sourceNode && this.analyser) {
        this.sourceNode.disconnect(this.analyser);
      }

      this.analyser = null;
      this.canvasContext = null;
      this.audioContext = null;
      this.sourceNode = null;
      this.visualizationMethods = null;
      this._frequencyData = null;
      this._timeData = null;
      this._frequencyMultipliers = null;

      console.log("Oscilloscope destroyed successfully");
    } catch (error) {
      console.error("Error destroying oscilloscope:", error);
    }
  }
}
