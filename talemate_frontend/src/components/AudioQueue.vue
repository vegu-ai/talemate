<template>
  <div class="audio-queue text-caption">
    <span class="text-grey mr-1">{{ queue.length }} sound(s) queued</span>
    
    <v-btn
      icon
      size="small"
      variant="text"
      density="compact"
      rounded="2"
      :color="isPlaying ? 'success' : ''"
      @click="toggleMute"
    >
      <v-tooltip activator="parent" location="top">Toggle mute</v-tooltip>
      <v-icon>{{ volumeIcon }}</v-icon>
    </v-btn>

    <span class="volume-control">
      <v-tooltip activator="parent" location="top">Volume</v-tooltip>
      <v-slider
        :model-value="volumeLocal"
        class="volume-slider"
        aria-label="Volume"
        :min="0"
        :max="1"
        :step="0.01"
        density="compact"
        hide-details
        thumb-size="10"
        track-size="2"
        @update:modelValue="onVolumeInput"
        @start="onVolumeDragStart"
        @end="onVolumeDragEnd"
        @update:focused="onVolumeFocusChange"
      ></v-slider>
    </span>

    <v-btn
      icon
      size="small"
      variant="text"
      density="compact"
      rounded="2"
      :disabled="!isPlaying && !isPaused"
      @click="togglePlayPause"
    >
      <v-tooltip activator="parent" location="top">{{ isPaused ? 'Resume playback' : 'Pause playback' }}</v-tooltip>
      <v-icon>{{ isPaused ? 'mdi-play-circle-outline' : 'mdi-pause-circle-outline' }}</v-icon>
    </v-btn>
    
    <v-btn
      icon
      size="small"
      variant="text"
      density="compact"
      rounded="2"
      :color="(isPlaying || isPaused) ? 'delete' : ''"
      :disabled="!isPlaying && !isPaused"
      @click="stopAndClear"
    >
      <v-tooltip activator="parent" location="top">Stop and clear the audio queue</v-tooltip>
      <v-icon>mdi-stop-circle-outline</v-icon>
    </v-btn>
  </div>
</template>

<script>
import { createSoundControl } from '@/utils/soundControl';

export default {
  name: 'AudioQueue',
  data() {
    return {
      queue: [],
      audioContext: null,
      gainNode: null,
      isPlaying: false,
      isPaused: false,
      currentSource: null,
      currentBuffer: null,
      currentAudioItem: null,
      pausedAt: 0,
      startedAt: 0,
      // built here rather than in created() so the computeds and watchers
      // below, which are set up first, can already read it
      soundControl: createSoundControl({
        save: (patch, options) => this.saveAppConfig((config) => {
          config.sound = { ...(config.sound || {}), ...patch };
        }, options),
        getSound: () => this.appConfig()?.sound
      })
    };
  },
  emits: ['message-audio-played'],
  inject: ['getWebsocket', 'registerMessageHandler', 'appConfig', 'saveAppConfig'],
  computed: {
    soundConfig() {
      return this.appConfig()?.sound;
    },
    volumeLocal() {
      return this.soundControl.state.volumeLocal;
    },
    isMuted() {
      return this.soundControl.isMuted();
    },
    effectiveVolume() {
      return this.soundControl.effectiveVolume();
    },
    effectiveGain() {
      return this.isMuted ? 0 : this.effectiveVolume;
    },
    volumeIcon() {
      if (this.isMuted) {
        return 'mdi-volume-off';
      } else if (this.effectiveVolume === 0) {
        return 'mdi-volume-mute';
      } else if (this.effectiveVolume <= 0.33) {
        return 'mdi-volume-low';
      } else if (this.effectiveVolume <= 0.66) {
        return 'mdi-volume-medium';
      }
      return 'mdi-volume-high';
    }
  },
  watch: {
    effectiveGain(value) {
      this.applyGain(value);
    },
    soundConfig() {
      this.soundControl.configChanged();
    }
  },
  created() {
    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    this.gainNode = this.audioContext.createGain();
    this.gainNode.connect(this.audioContext.destination);
    this.soundControl.configChanged();
    this.applyGain(this.effectiveGain);
    this.registerMessageHandler(this.handleMessage);
  },
  methods: {
    applyGain(value) {
      this.gainNode.gain.value = value;
    },
    handleMessage(data) {
      if (data.type === 'audio_queue') {
        this.addToQueue(data.data.audio_data, data.data.message_id);
      }
    },
    addToQueue(base64Sound, messageId = null) {
      const soundBuffer = this.base64ToArrayBuffer(base64Sound);
      this.queue.push({
        buffer: soundBuffer,
        messageId: messageId
      });
      if (!this.isPaused) {
        this.playNextSound();
      }
    },
    base64ToArrayBuffer(base64) {
      const binaryString = window.atob(base64);
      const len = binaryString.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      return bytes.buffer;
    },
    playNextSound() {
      if (this.isPlaying || this.isPaused || this.queue.length === 0) {
        return;
      }
      this.isPlaying = true;
      this.pausedAt = 0;
      const audioItem = this.queue.shift();
      this.currentAudioItem = audioItem;
      this.audioContext.decodeAudioData(audioItem.buffer, (buffer) => {
        this.currentBuffer = buffer;
        this.playBuffer(0);
      }, (error) => {
        console.error('Error with decoding audio data', error);
        this.isPlaying = false;
        this.currentAudioItem = null;
        this.playNextSound();
      });
    },
    playBuffer(offset) {
      const source = this.audioContext.createBufferSource();
      source.buffer = this.currentBuffer;
      this.currentSource = source;
      source.connect(this.gainNode);
      source.onended = () => {
        if (!this.isPaused) {
          this.isPlaying = false;
          this.currentBuffer = null;
          this.currentAudioItem = null;
          this.pausedAt = 0;
          this.$emit('message-audio-played', undefined);
          this.playNextSound();
        }
      };
      this.startedAt = this.audioContext.currentTime - offset;
      source.start(0, offset);
      
      // Emit message-audio-played event if this audio has a message_id
      if (this.currentAudioItem) {
        this.$emit('message-audio-played', this.currentAudioItem.messageId);
      }
    },
    pause() {
      if (!this.isPlaying || this.isPaused) {
        return;
      }
      this.isPaused = true;
      this.pausedAt = this.audioContext.currentTime - this.startedAt;
      if (this.currentSource) {
        this.currentSource.stop();
        this.currentSource.disconnect();
        this.currentSource = null;
      }
    },
    resume() {
      if (!this.isPaused) {
        return;
      }
      this.isPaused = false;
      if (this.currentBuffer) {
        this.playBuffer(this.pausedAt);
      } else {
        this.isPlaying = false;
        this.currentAudioItem = null;
        this.playNextSound();
      }
    },
    toggleMute() {
      this.soundControl.toggleMute();
    },
    onVolumeInput(value) {
      this.soundControl.input(value);
    },
    onVolumeDragStart() {
      this.soundControl.dragStart();
    },
    onVolumeDragEnd(value) {
      this.soundControl.dragEnd(value);
    },
    onVolumeFocusChange(focused) {
      this.soundControl.setFocused(focused);
    },
    togglePlayPause() {
      if (this.isPaused) {
        this.resume();
      } else if (this.isPlaying) {
        this.pause();
      }
    },
    stopAndClear() {
      // Inform backend to cancel generation and clear queue
      try {
        this.getWebsocket().send(
          JSON.stringify({ type: 'tts', action: 'stop_and_clear' })
        );
      } catch (e) {
        // websocket may not be available yet; ignore errors here
        console.warn('Failed to send stop_and_clear', e);
      }

      if (this.currentSource) {
        this.currentSource.stop();
        this.currentSource.disconnect();
        this.currentSource = null;
      }
      this.queue = [];
      this.isPlaying = false;
      this.isPaused = false;
      this.currentBuffer = null;
      this.currentAudioItem = null;
      this.pausedAt = 0;
      this.startedAt = 0;
    }
  }
};
</script>

<style scoped>
.audio-queue {
  display: flex;
  align-items: center;
}

.volume-control {
  display: flex;
  align-items: center;
  flex: 0 0 80px;
}

.audio-queue :deep(.volume-slider.v-input--horizontal) {
  margin-inline: 4px;
}

/* the queue lives in the system bar, whose height is fixed at 24px — the
   slider's default control height would push its content out of the bar */
.audio-queue :deep(.volume-slider.v-input--horizontal > .v-input__control) {
  min-height: 0;
}
</style>
