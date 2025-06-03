#!/bin/sh
. talemate_env/bin/activate
TALEMATE_DEBUG=1 python src/talemate/server/run.py runserver --host 0.0.0.0 --port 5050 --backend-only