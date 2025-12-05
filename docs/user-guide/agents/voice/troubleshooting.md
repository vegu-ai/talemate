# TTS Troubleshooting

Common issues and solutions for Text-to-Speech functionality in Talemate.

## FFmpeg Not Found

Several TTS providers (including [Chatterbox](chatterbox.md) and [F5-TTS](f5tts.md)) require FFmpeg for audio processing.

!!! note "Auto-Installation"
    FFmpeg is automatically installed during the initial Talemate installation on Windows. If you encounter FFmpeg errors, the installation may have failed or been skipped.

### Symptoms

You may encounter errors like:

```
Could not load libtorchcodec. Likely causes:
 1. FFmpeg is not properly installed in your environment. We support
 versions 4, 5, 6, 7, and 8.
 2. The PyTorch version is not compatible with this version of TorchCodec.
```

Or:

```
FFmpeg version 8: Could not load this library
```

Or generic FFmpeg-related import/loading errors.

### Solution

#### Windows

Run the included `install-ffmpeg.bat` script from the Talemate root directory:

```batch
install-ffmpeg.bat
```

This will automatically download and install FFmpeg 8.0.1 into your virtual environment.

#### Linux/macOS

Install FFmpeg using your system's package manager. FFmpeg versions 4, 5, 6, 7, or 8 are supported.

### Verification

After installing FFmpeg, verify it's accessible by running:

```bash
ffmpeg -version
```

You should see output showing the FFmpeg version (4.x, 5.x, 6.x, 7.x, or 8.x are all supported).

**Important:** Restart Talemate after installing FFmpeg for the changes to take effect.