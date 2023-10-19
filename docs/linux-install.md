### Setting Up a Virtual Environment

1. Open a terminal.
2. Navigate to the project directory.
3. Create a virtual environment by running `python3 -m venv talemate_env`.
4. Activate the virtual environment by running `source talemate_env/bin/activate`.

### Installing Dependencies

1. With the virtual environment activated, install poetry by running `pip install poetry`.
2. Use poetry to install dependencies by running `poetry install`.

### Running the Backend

1. With the virtual environment activated and dependencies installed, you can start the backend server.
2. Navigate to the `src/talemate/server` directory.
3. Run the server with `python run.py runserver --host 0.0.0.0 --port 5050`.

### Running the Frontend

1. Navigate to the `talemate_frontend` directory.
2. If you haven't already, install npm dependencies by running `npm install`.
3. Start the server with `npm run serve`.

Please note that you may need to set environment variables or modify the host and port as per your setup. You can refer to the `runserver.sh` and `frontend.sh` files for more details.
