@echo off
cd /d "%~dp0"

venv\Scripts\python.exe -c "from app import app, db; db.create_all(); print('DB ready')"
if errorlevel 1 (
    echo DB init failed, checking if tables exist...
)

venv\Scripts\python.exe -c "
import os, sys
os.environ['SECRET_KEY'] = 'dev-secret-key-change-in-production'
sys.path.insert(0, os.getcwd())
from app import app
app.run(debug=True, host='127.0.0.1', port=5000, use_reloader=False)
"