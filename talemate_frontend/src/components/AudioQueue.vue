<template>
  <div class="audio-queue">
    <span>{{ queue.length }} sound(s) queued</span>
    <v-icon :color="isPlaying ? 'green' : ''" v-if="!isMuted" @click="toggleMute">mdi-volume-high</v-icon>
    <v-icon :color="isPlaying ? 'red' : ''" v-else @click="toggleMute">mdi-volume-off</v-icon>
    <v-icon v-if="isPlaying" class="ml-1" @click="stopAndClear">mdi-stop-circle-outline</v-icon>
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
      isMuted: false,
      currentSource: null
    };
  },
  inject: ['getWebsocket', 'registerMessageHandler'],
  created() {
    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    this.registerMessageHandler(this.handleMessage);
  },
  methods: {
    handleMessage(data) {
      if (data.type === 'audio_queue') {
        console.log('Received audio queue message', data)
        this.addToQueue(data.data.audio_data);
      }
    },
    addToQueue(base64Sound) {
      const soundBuffer = this.base64ToArrayBuffer(base64Sound);
      this.queue.push(soundBuffer);
      this.playNextSound();
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
      if (this.isPlaying || this.queue.length === 0) {
        return;
      }
      this.isPlaying = true;
      const soundBuffer = this.queue.shift();
      this.audioContext.decodeAudioData(soundBuffer, (buffer) => {
        const source = this.audioContext.createBufferSource();
        source.buffer = buffer;
        this.currentSource = source;
        if (!this.isMuted) {
          source.connect(this.audioContext.destination);
        }
        source.onended = () => {
          this.isPlaying = false;
          this.playNextSound();
        };
        source.start(0);
      }, (error) => {
        console.error('Error with decoding audio data', error);
      });
    },
    toggleMute() {
      this.isMuted = !this.isMuted;
      if (this.isMuted && this.currentSource) {
        this.currentSource.disconnect(this.audioContext.destination);
      } else if (this.currentSource) {
        this.currentSource.connect(this.audioContext.destination);
      }
    },
    stopAndClear() {
      if (this.currentSource) {
        this.currentSource.stop();
        this.currentSource.disconnect();
        this.currentSource = null;
      }
      this.queue = [];
      this.isPlaying = false;
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
