import os
import subprocess
import sys
import pandas as pd
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from typing import Dict, Any
from typing import Optional
from pathlib import Path

def get_data_dir():
    """获取用户数据目录"""
    if sys.platform == "darwin":  # macOS
        return os.path.expanduser("~/Library/Application Support/YourAppName")
    elif sys.platform == "win32":  # Windows
        return os.path.expanduser("~/AppData/Local/YourAppName")
    else:  # Linux
        return os.path.expanduser("~/.local/share/YourAppName")

def setup_static_directory():
    """设置静态文件目录"""
    if hasattr(sys, '_MEIPASS'):
        # 打包后：在用户数据目录创建
        static_dir = os.path.join(get_data_dir(), "static")
    else:
        # 开发模式：在当前目录创建
        static_dir = "static"
    
    os.makedirs(static_dir, exist_ok=True)
    return static_dir

# Global variable to store the subprocess reference
watch_process: Optional[subprocess.Popen] = None

def output_reader(pipe, name):
    """从管道读取输出并打印"""
    for line in pipe:
        print(f"[{name}] {line.strip()}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the fluctuation watch
    global watch_process
    try:
        watch_process = subprocess.Popen(
            [sys.executable, "fluctuation.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # 行缓冲
            universal_newlines=True
        )
        print(f"Started fluctuation watch with PID: {watch_process.pid}")
        
        # 启动输出读取线程
        import threading
        threading.Thread(
            target=output_reader, 
            args=(watch_process.stdout, "fluctuation"),
            daemon=True
        ).start()
        
        # 启动错误输出读取线程
        threading.Thread(
            target=output_reader,
            args=(watch_process.stderr, "fluctuation-err"),
            daemon=True
        ).start()
        
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

CHANGES_BY_CONCEPT_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>盘口异动</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/umbrellajs"></script>
    <script>
        function loadData() {
            fetch('http://0.0.0.0:61115/api/changes/json', {
                method: 'GET',
                headers: {
                    'Accept': 'application/json'
                }
            })
            .then(function(response) {
                if (!response.ok) throw new Error('Network response was not ok');
                return response.json();
            })
            .then(function(data) {
                if (data && data.length > 0) {
                    const concepts = {};
                    data.forEach(item => {
                        const conceptName = item["板块名称"];
                        if (!concepts[conceptName]) {
                            concepts[conceptName] = { "上午": {}, "下午": {} };
                        }
                        
                        const time = item["时间"];
                        const name = item["名称"];
                        const roundedValue = item["四舍五入取整"];
                        const type = item["类型"];

                        let valueStr = roundedValue > 0 ? `+${roundedValue}` : roundedValue;

                        if (type === "封涨停板") {
                            valueStr = `<span class='text-red-600'>${valueStr}</span>`;
                        }

                        const info = `<span>${name} ${type} ${valueStr}</span>`;
                        const period = item["上下午"];

                        if (period === "上午" || period === "下午") {
                            if (!concepts[conceptName][period][time]) {
                                concepts[conceptName][period][time] = [];
                            }
                            concepts[conceptName][period][time].push(info);
                        }
                    });

                    let tableBodyHtml = '';
                    for (const conceptName in concepts) {
                        let rowHtml = '<tr>';
                        rowHtml += `<td class="p-2 font-semibold align-top border">${conceptName}</td>`;

                        for (const period of ["上午", "下午"]) {
                            let periodHtml = '<td class="p-2 align-top border">';
                            const timeGroups = concepts[conceptName][period];
                            const sortedTimes = Object.keys(timeGroups).sort();

                            for (const time of sortedTimes) {
                                const stocks = timeGroups[time].join(', ');
                                periodHtml += `<p>${time} ${stocks}</p>`;
                            }
                            periodHtml += '</td>';
                            rowHtml += periodHtml;
                        }

                        rowHtml += '</tr>';
                        tableBodyHtml += rowHtml;
                    }
                    
                    u('#concepts-body').html(tableBodyHtml);
                    
                    u('#loading').addClass('hidden');
                    u('#data-container').removeClass('hidden');
                } else {
                    u('#loading').html('No data available');
                }
            })
            .catch(function(error) {
                console.error('Error loading data:', error);
                u('#loading').html('Error loading data. Please try again later.');
            });
        }
        
        function isTradingHours() {
            const options = { 
                timeZone: 'Asia/Shanghai',
                hour: 'numeric',
                minute: 'numeric',
                weekday: 'long',
                hour12: false
            };
            
            const now = new Date();
            const beijingTime = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }));
            const day = beijingTime.getDay();
            const hours = beijingTime.getHours();
            const minutes = beijingTime.getMinutes();
            const currentMinutes = hours * 60 + minutes;
            
            const isTrading = day >= 1 && day <= 5 && 
                             ((currentMinutes >= 9 * 60 + 30 && currentMinutes < 11 * 60 + 30) || 
                              (currentMinutes >= 13 * 60 && currentMinutes < 15 * 60));
            
            console.log('Beijing Time:', beijingTime);
            console.log('Day:', day, 'Time:', hours + ':' + minutes);
            console.log('Is trading hours:', isTrading);
            return isTrading;
        }
        
        document.addEventListener('DOMContentLoaded', function() {
            function checkAndLoadData() {
                if (isTradingHours()) {
                    u('#loading').removeClass('hidden').html('正在更新数据...');
                    u('#data-container').addClass('hidden');
                    loadData();
                } else {
                    u('#loading').removeClass('hidden').html('当前非交易时间（交易时间：周一至周五 9:30-11:30, 13:00-15:00 北京时间）');
                    u('#data-container').addClass('hidden');
                }
            }
            
            checkAndLoadData();
            
            setInterval(checkAndLoadData, 2000);
        });
    </script>
</head>
<body class="bg-gray-100 p-6">
    <div class="container mx-auto bg-white rounded-lg shadow-md p-6 max-w-7xl">
        <h1 class="text-2xl font-bold text-gray-800 text-center mb-6">盘口异动</h1>
        <div class="mt-6">
            <div id="loading" class="text-center py-4">Loading data...</div>
            <div id="data-container" class="hidden">
                <table class="w-full text-xs border-collapse table-fixed">
                    <thead>
                        <tr class="bg-amber-100">
                            <th class="p-2 border" style="width: 10%;">板块</th>
                            <th class="p-2 border" style="width: 45%;">上午</th>
                            <th class="p-2 border" style="width: 45%;">下午</th>
                        </tr>
                    </thead>
                    <tbody id="concepts-body" class="divide-y divide-gray-200">
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>"""

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return RedirectResponse(url="/changes_by_concept")

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
    return HTMLResponse(content=CHANGES_BY_CONCEPT_HTML, media_type="text/html")

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
   # 检查是否为打包后的执行文件
    is_packaged = hasattr(sys, '_MEIPASS')
    static_path = setup_static_directory()

    if is_packaged:
        # 打包后直接运行app对象，而不是字符串引用
        uvicorn.run(
            app,  # 直接传递app对象，而不是"main:app"
            host="0.0.0.0", 
            port=61125,
            reload=False
        )
    else:
        # 开发模式
        uvicorn.run(
            "main:app", 
            host="0.0.0.0", 
            port=61115,
            reload=True
        )
