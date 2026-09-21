@echo off
cd /d "C:\Users\cheng\Documents\akshare-test\gift_bookkeeping_app"
start "" /B "C:\Users\cheng\AppData\Local\Programs\Python\Python312\python.exe" app.py > ".temp\app_out.log" 2> ".temp\app_err.log"
