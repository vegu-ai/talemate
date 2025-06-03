REM activate the virtual environment
call talemate_env\Scripts\activate

REM uninstall torch and torchaudio
python -m pip uninstall torch torchaudio -y

REM install torch and torchaudio
python -m pip install torch~=2.7.0 torchaudio~=2.7.0 --index-url https://download.pytorch.org/whl/cu128