import os
import subprocess
import sys
import pandas as pd
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from typing import Optional

# Global variable to store the subprocess reference
watch_process: Optional[subprocess.Popen] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the fluctuation watch
    global watch_process
    try:
        watch_process = subprocess.Popen(
            [sys.executable, "fluctuation.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print(f"Started fluctuation watch with PID: {watch_process.pid}")
        yield
    finally:
        # Shutdown: Stop the fluctuation watch
        if watch_process:
            watch_process.terminate()
            try:
                watch_process.wait(timeout=5)
                print("Fluctuation watch stopped gracefully")
            except subprocess.TimeoutExpired:
                watch_process.kill()
                print("Fluctuation watch was force stopped")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return RedirectResponse(url="/changes_by_concept")

# Create static directory if it doesn't exist
os.makedirs("static", exist_ok=True)

@app.get("/api/changes/csv")
async def get_changes_csv():
    """Get changes data in CSV format"""
    csv_path = "static/changes.csv"
    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail="CSV file not found")
    return FileResponse(csv_path, media_type="text/csv", filename="changes.csv")

@app.get("/api/changes/json")
async def get_changes_json():
    """Get changes data in JSON format"""
    csv_path = "static/changes.csv"
    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail="CSV file not found")
    
    try:
        # Read CSV and fill NaN values with None
        df = pd.read_csv(csv_path)
        # Convert DataFrame to list of dicts, replacing NaN with None
        data = df.where(pd.notnull(df), None).to_dict(orient="records")
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading CSV: {str(e)}")

@app.get("/changes_by_concept", response_class=HTMLResponse)
async def get_changes_by_concept():
    with open("templates/changes_by_concept.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), media_type="text/html")

@app.get("/api/watch/status")
async def get_watch_status():
    """Get the status of the fluctuation watch process"""
    global watch_process
    if watch_process is None:
        return {"status": "not_running"}
    
    return_code = watch_process.poll()
    if return_code is None:
        return {"status": "running", "pid": watch_process.pid}
    else:
        return {"status": "stopped", "return_code": return_code}

@app.post("/api/watch/restart")
async def restart_watch():
    """Restart the fluctuation watch process"""
    global watch_process
    
    # Stop existing process if running
    if watch_process:
        watch_process.terminate()
        try:
            watch_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            watch_process.kill()
    
    # Start new process
    watch_process = subprocess.Popen(
        [sys.executable, "fluctuation.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    return {"status": "restarted", "pid": watch_process.pid}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=61125, reload=True)
