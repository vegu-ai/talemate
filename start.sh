#!/bin/sh
. talemate_env/bin/activate
python src/talemate/server/run.py runserver --host 0.0.0.0 --port 5050