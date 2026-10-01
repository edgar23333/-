@echo off
cd /d "%~dp0"
echo WeChat Auto Sender V14.0 - Environment Check
echo.
if not exist "assets\edgar_avatar.png" goto fail_asset
if not exist "assets\edgar_avatar.ico" goto fail_asset
echo Avatar assets OK
py -3.11 -c "import sys; print('Python:',sys.version); print('Bits:',8*(__import__('struct').calcsize('P'))); assert sys.maxsize > 2**32"
if errorlevel 1 goto fail
py -3.11 -c "import pyautogui; print('pyautogui OK')"
if errorlevel 1 goto fail
py -3.11 -c "from PIL import Image; print('Pillow OK')"
if errorlevel 1 goto fail
py -3.11 -c "import win32api; print('pywin32 OK')"
if errorlevel 1 goto fail
py -3.11 -c "from rapidocr import RapidOCR; print('RapidOCR OK')"
if errorlevel 1 goto fail
py -3.11 -c "import onnxruntime; print('ONNX Runtime:',onnxruntime.__version__)"
if errorlevel 1 goto fail
py -3.11 -c "import cv2; print('OpenCV:',cv2.__version__)"
if errorlevel 1 goto fail
py -3.11 -c "import PyInstaller; print('PyInstaller:',PyInstaller.__version__)"
if errorlevel 1 goto fail
echo.
echo All checks passed.
pause
exit /b 0
:fail_asset
echo ERROR: assets\edgar_avatar.png or assets\edgar_avatar.ico is missing.
pause
exit /b 1
:fail
echo.
echo Some checks failed.
pause
exit /b 1
