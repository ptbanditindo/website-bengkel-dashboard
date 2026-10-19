@echo off
setlocal EnableExtensions
chcp 65001 >nul
title AI Bengkel - Kontrol Layanan
cd /d "%~dp0"

if not exist "logs" mkdir logs

:menu
cls
echo ==================================================
echo   AI Bengkel - Kontrol Layanan
echo ==================================================
echo   1. Start semua layanan
echo   2. Restart semua layanan
echo   3. Stop semua layanan
echo   4. Buka Dashboard (browser)
echo   5. Cek status layanan
echo   6. Keluar
echo ==================================================
set "pilih="
set /p "pilih=Pilih nomor (1-6): "

if "%pilih%"=="1" call :start_all
if "%pilih%"=="2" call :start_all
if "%pilih%"=="3" call :do_stop
if "%pilih%"=="4" call :open_dashboard
if "%pilih%"=="5" call :status
if "%pilih%"=="6" exit /b 0
goto menu

rem ------------------------------------------------------------------
rem Start (dan restart = stop dulu + start lagi) semua layanan.
rem ------------------------------------------------------------------
:start_all
if not exist ".env" (
    echo.
    echo [ERROR] File .env tidak ditemukan.
    echo         Salin .env.example menjadi .env lalu isi konfigurasinya.
    echo.
    pause
    exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Python tidak ditemukan di PATH.
    echo.
    pause
    exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Node.js tidak ditemukan di PATH.
    echo.
    pause
    exit /b 1
)

call :stop_all >nul 2>&1
echo.
echo Menjalankan layanan di latar belakang...
echo   [1/3] API + Dashboard  (http://127.0.0.1:8000/ui)
powershell -NoProfile -Command "$p = Start-Process -FilePath 'python.exe' -ArgumentList 'run_api.py' -WorkingDirectory (Get-Location) -WindowStyle Hidden -RedirectStandardOutput 'logs\api.log' -RedirectStandardError 'logs\api.err.log' -PassThru; Set-Content 'logs\api.pid' -Value $p.Id -Encoding ascii"
echo   [2/3] Bot Telegram
powershell -NoProfile -Command "$p = Start-Process -FilePath 'python.exe' -ArgumentList 'main.py' -WorkingDirectory (Get-Location) -WindowStyle Hidden -RedirectStandardOutput 'logs\telegram.log' -RedirectStandardError 'logs\telegram.err.log' -PassThru; Set-Content 'logs\telegram.pid' -Value $p.Id -Encoding ascii"
echo   [3/3] Gateway WhatsApp (Baileys)
powershell -NoProfile -Command "$p = Start-Process -FilePath 'node.exe' -ArgumentList 'gateway\whatsapp_bridge.js' -WorkingDirectory (Get-Location) -WindowStyle Hidden -RedirectStandardOutput 'logs\whatsapp.log' -RedirectStandardError 'logs\whatsapp.err.log' -PassThru; Set-Content 'logs\whatsapp.pid' -Value $p.Id -Encoding ascii"
echo.
echo Selesai. Log tersimpan di folder "logs".
echo.
pause
exit /b 0

rem ------------------------------------------------------------------
rem Stop semua layanan (pembungkus menu).
rem ------------------------------------------------------------------
:do_stop
call :stop_all
echo.
echo Semua layanan dihentikan.
echo.
pause
exit /b 0

rem ------------------------------------------------------------------
rem Stop semua layanan (murni: matikan PID + hapus file pid).
rem ------------------------------------------------------------------
:stop_all
powershell -NoProfile -Command "Get-ChildItem 'logs\*.pid' | ForEach-Object { $procId = (Get-Content $_.FullName) -as [int]; if ($procId) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }; Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }"
exit /b 0

rem ------------------------------------------------------------------
rem Buka dashboard di browser.
rem ------------------------------------------------------------------
:open_dashboard
start "" http://127.0.0.1:8000/ui
echo.
echo Dashboard dibuka di browser: http://127.0.0.1:8000/ui
echo.
pause
exit /b 0

rem ------------------------------------------------------------------
rem Cek status tiap layanan.
rem ------------------------------------------------------------------
:status
echo.
echo Status layanan:
powershell -NoProfile -Command "foreach ($f in Get-ChildItem 'logs\*.pid') { $n = $f.BaseName; $id = (Get-Content $f.FullName) -as [int]; $p = Get-Process -Id $id -ErrorAction SilentlyContinue; if ($p) { Write-Host ('  ' + $n + '  : RUNNING  (PID ' + $id + ')') } else { Write-Host ('  ' + $n + '  : STOPPED') } }"
echo.
echo (Jika tidak ada baris status di atas, belum ada layanan yang di-start.)
echo.
pause
exit /b 0
