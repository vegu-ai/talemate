<template>
  <div class="audio-queue text-body-small">
    <span class="text-medium-emphasis mr-1">{{ queue.length }} sound(s) queued</span>
    
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
import { chunkIsAbandoned } from '@/utils/playthrough';

export default {
  name: 'AudioQueue',
  data() {
    return {
      queue: [],
      audioContext: null,
      gainNode: null,
      isPlaying: false,
      isPaused: false,
      // message whose generation the backend has reported finished; it is
      // only *done* once whatever it queued has also played out
      pendingCompletion: null,
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
  props: {
    // messages whose narration was superseded before it finished generating.
    // Their chunks are still in flight and would narrate a message the reader
    // has already stepped past. Scoped to those ids on purpose: this is the
    // application-wide queue, so anything else - a voice test, a message played
    // by hand - has to keep playing.
    staleMessageIds: {
      type: Array,
      default: () => [],
    },
  },
  emits: ['message-audio-played', 'message-audio-finished'],
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
        if (data.data.generation_complete) {
          this.pendingCompletion = data.data.message_id;
          this.emitFinishedIfDone();
          return;
        }
        this.addToQueue(data.data.audio_data, data.data.message_id);
      }
    },

    // A gap between two chunks of the same message empties the queue without
    // the message being over, so an empty queue only means "finished" once
    // the backend has said it is done generating for that message.
    emitFinishedIfDone() {
      if (this.pendingCompletion === null) {
        return;
      }
      if (this.isPlaying || this.isPaused || this.queue.length) {
        return;
      }
      const messageId = this.pendingCompletion;
      this.pendingCompletion = null;
      this.$emit('message-audio-finished', messageId);
    },
    addToQueue(base64Sound, messageId = null) {
      if (chunkIsAbandoned(messageId, this.staleMessageIds)) {
        // audio for a message that has already been stepped past; playing it
        // would narrate one message while another is on screen
        return;
      }
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
        // a failed decode on the last chunk would otherwise strand whoever is
        // waiting for the message to finish
        this.emitFinishedIfDone();
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
          this.emitFinishedIfDone();
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
      // a stop is not a message finishing - whoever was waiting on it was
      // told to stop waiting by the same action that stopped playback
      this.pendingCompletion = null;
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
