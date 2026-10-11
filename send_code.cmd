@echo off
rem Sends the code to the Pi, builds it there, and starts Knightscribe. Keep this window open while using it.
rem Change PI_USER / PI_HOST if your Pi uses different ones (use its IP address if knightcribe.local doesn't work).
set PI_USER=jvertus
set PI_HOST=knightcribe.local
set PI_DIR=/home/%PI_USER%/knightcribe/Knightcribe-Starter

cd /d "%~dp0"

echo Waiting for the Pi at %PI_HOST% (gives up after about 2 minutes)...
set /a tries=0
:wait
ping -n 1 -w 2000 %PI_HOST% >nul 2>&1
if not errorlevel 1 goto up
set /a tries+=1
if %tries% GEQ 40 goto fail
echo   still waiting... (%tries%/40)
timeout /t 1 /nobreak >nul
goto wait

:up
echo Pi found.
rem A freshly flashed Pi has a new identity: forget the old one so ssh does not refuse, and trust the new one.
ssh-keygen -R %PI_HOST% >nul 2>&1
set SSH_OPTS=-o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new
echo [1/3] Making the project folder on the Pi - type the Pi password:
ssh %SSH_OPTS% %PI_USER%@%PI_HOST% "mkdir -p %PI_DIR%"
if errorlevel 1 goto fail
echo.
echo [2/3] Copying code to the Pi - type the Pi password again:
scp %SSH_OPTS% knightcribe.cpp web.py transcribe.py live_captions.py export.py CMakeLists.txt README.md .gitignore pi_start.sh test_camera.sh %PI_USER%@%PI_HOST%:%PI_DIR%/
if errorlevel 1 goto fail
echo.
echo [3/3] Building and starting on the Pi - type the Pi password once more:
ssh -t %SSH_OPTS% %PI_USER%@%PI_HOST% "bash %PI_DIR%/pi_start.sh"
pause
exit /b
:fail
echo FAILED - could not reach the Pi. Is it on and connected? (If %PI_HOST% doesn't work, set PI_HOST to the Pi's IP address, e.g. 192.168.137.x.)
pause
