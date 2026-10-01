@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==================================================
echo WeChat Auto Sender V14.0 - Slim Release Builder
echo ==================================================
echo.

echo [1/8] Checking source assets...
if not exist "assets\edgar_avatar.png" goto missing_asset
if not exist "assets\edgar_avatar.ico" goto missing_asset

echo [2/8] Checking WeChatAutoSender.exe is not running...
tasklist /FI "IMAGENAME eq WeChatAutoSender.exe" 2>NUL | find /I "WeChatAutoSender.exe" >NUL
if not errorlevel 1 (
  echo ERROR: WeChatAutoSender.exe is currently running.
  echo Close it and run this file again.
  echo.
  pause
  exit /b 1
)

echo [3/8] Checking Python 3.11 x64...
py -3.11 -c "import sys; print(sys.version); assert sys.maxsize > 2**32"
if errorlevel 1 (
  echo ERROR: Python 3.11 x64 was not found.
  pause
  exit /b 1
)

echo [4/8] Checking required packages...
py -3.11 -c "import pyautogui, PIL, win32api, rapidocr, onnxruntime, cv2, PyInstaller; print('Dependencies OK')"
if errorlevel 1 (
  echo ERROR: Required packages are missing. Run check_environment.bat first.
  pause
  exit /b 1
)

echo [5/8] Checking Python source syntax...
py -3.11 -m compileall -q .
if errorlevel 1 (
  echo ERROR: Python syntax check failed.
  pause
  exit /b 1
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist WeChatAutoSender.spec del /f /q WeChatAutoSender.spec

echo [6/8] Building slim EXE...
rem Slim strategy:
rem - RapidOCR: collect Python submodules + packaged model/data files only.
rem - ONNX Runtime: collect its native binaries only; do not use --collect-all.
rem - No developer data folder is bundled.
py -3.11 -m PyInstaller --noconfirm --clean --onedir --noconsole --name WeChatAutoSender --icon "assets\edgar_avatar.ico" --add-data "assets;assets" --collect-submodules rapidocr --collect-data rapidocr --collect-binaries onnxruntime --hidden-import onnxruntime --hidden-import onnxruntime.capi._pybind_state --hidden-import win32api --hidden-import win32con --hidden-import win32gui --hidden-import win32clipboard --hidden-import win32process main.py
if errorlevel 1 (
  echo.
  echo BUILD FAILED.
  pause
  exit /b 1
)

echo [7/8] Copying and checking release assets...
if not exist "dist\WeChatAutoSender\assets" mkdir "dist\WeChatAutoSender\assets"
copy /Y "assets\edgar_avatar.png" "dist\WeChatAutoSender\assets\edgar_avatar.png" >NUL
copy /Y "assets\edgar_avatar.ico" "dist\WeChatAutoSender\assets\edgar_avatar.ico" >NUL
if not exist "dist\WeChatAutoSender\assets\edgar_avatar.png" goto post_fail
if not exist "dist\WeChatAutoSender\assets\edgar_avatar.ico" goto post_fail
if not exist "dist\WeChatAutoSender\WeChatAutoSender.exe" goto post_fail

rem Deliberately do NOT copy the developer's data/ directory.
if exist "dist\WeChatAutoSender_V14.0_Portable.zip" del /f /q "dist\WeChatAutoSender_V14.0_Portable.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\WeChatAutoSender\*' -DestinationPath 'dist\WeChatAutoSender_V14.0_Portable.zip' -Force"
if errorlevel 1 goto post_fail

echo [8/8] Release verification...
for /f %%A in ('powershell -NoProfile -Command "(Get-ChildItem -LiteralPath 'dist\\WeChatAutoSender' -Recurse -File ^| Measure-Object -Property Length -Sum).Sum"') do set SIZE=%%A
set /a SIZE_MB=(SIZE+1048575)/1048576
if not exist "dist\WeChatAutoSender_V14.0_Portable.zip" goto post_fail

echo.
echo ==================================================
echo BUILD SUCCESS
echo ==================================================
echo EXE: %CD%\dist\WeChatAutoSender\WeChatAutoSender.exe
echo ZIP: %CD%\dist\WeChatAutoSender_V14.0_Portable.zip
echo Release size (uncompressed): %SIZE_MB% MB
echo Avatar: dist\WeChatAutoSender\assets\edgar_avatar.png
echo ==================================================
echo.
echo Build finished. This window will stay open.
pause
endlocal
exit /b 0

:missing_asset
echo ERROR: Avatar assets are missing from the source folder.
echo Expected: assets\edgar_avatar.png and assets\edgar_avatar.ico
pause
exit /b 1

:post_fail
echo.
echo BUILD FAILED: one or more release files are missing.
pause
exit /b 1
