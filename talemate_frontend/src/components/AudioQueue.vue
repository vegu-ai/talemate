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
      <v-icon>{{ isMuted ? 'mdi-volume-off' : 'mdi-volume-high' }}</v-icon>
    </v-btn>
    
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
export default {
  name: 'AudioQueue',
  data() {
    return {
      queue: [],
      audioContext: null,
      isPlaying: false,
      isPaused: false,
      isMuted: false,
      currentSource: null,
      currentBuffer: null,
      currentAudioItem: null,
      pausedAt: 0,
      startedAt: 0
    };
  },
  emits: ['message-audio-played'],
  inject: ['getWebsocket', 'registerMessageHandler'],
  created() {
    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    this.registerMessageHandler(this.handleMessage);
  },
  methods: {
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
      if (!this.isMuted) {
        source.connect(this.audioContext.destination);
      }
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
      this.isMuted = !this.isMuted;
      if (this.isMuted && this.currentSource) {
        this.currentSource.disconnect(this.audioContext.destination);
      } else if (this.currentSource) {
        this.currentSource.connect(this.audioContext.destination);
      }
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
</style>
