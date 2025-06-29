@echo off

REM Check if .venv exists
IF NOT EXIST ".venv" (
    echo [ERROR] .venv directory not found. Please run install.bat first.
    goto :eof
)

REM Check if embedded Python exists
IF NOT EXIST "embedded_python\python.exe" (
    echo [ERROR] embedded_python not found. Please run install.bat first.
    goto :eof
)

REM uninstall torch and torchaudio using embedded Python's uv
embedded_python\python.exe -m uv pip uninstall torch torchaudio --python .venv\Scripts\python.exe

REM install torch and torchaudio with CUDA support using embedded Python's uv
embedded_python\python.exe -m uv pip install torch~=2.7.0 torchaudio~=2.7.0 --index-url https://download.pytorch.org/whl/cu128 --python .venv\Scripts\python.exe

echo.
echo CUDA versions of torch and torchaudio installed!
echo You may need to restart your application for changes to take effect.