import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

# Get the directory of the current file
current_dir = os.path.dirname(os.path.abspath(__file__))
# Construct the path to the dist directory
dist_dir = os.path.join(current_dir, "talemate_frontend", "dist")

app = FastAPI()

# Serve static files, but exclude the root path
app.mount("/", StaticFiles(directory=dist_dir, html=True), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_root():
    index_path = os.path.join(dist_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            content = f.read()
        return HTMLResponse(content=content)
    else:
        raise HTTPException(status_code=404, detail="index.html not found")

# This is the ASGI application
application = app