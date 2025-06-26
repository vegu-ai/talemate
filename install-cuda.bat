REM uninstall torch and torchaudio
uv pip uninstall torch torchaudio

REM install torch and torchaudio with CUDA support
uv pip install torch~=2.7.0 torchaudio~=2.7.0 --index-url https://download.pytorch.org/whl/cu128