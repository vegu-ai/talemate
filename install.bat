@echo off

REM create a virtual environment
python -m venv talemate_env

REM activate the virtual environment
call talemate_env\Scripts\activate

REM activate the virtual environment
call talemate_env\Scripts\activate

REM install poetry
python -m pip install "poetry==1.7.1" "rapidfuzz>=3" -U

REM copy config.example.yaml to config.yaml only if config.yaml doesn't exist
IF NOT EXIST config.yaml copy config.example.yaml config.yaml

REM navigate to the frontend directory
cd talemate_frontend
npm install

REM return to the root directory
cd ..

echo Installation completed successfully.
pause
