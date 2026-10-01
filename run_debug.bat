@echo off
cd /d "%~dp0"
echo Starting WeChat Auto Sender V14.0...
echo.
py -3.11 main.py
if errorlevel 1 echo.
if errorlevel 1 echo Program exited with an error.
pause
