@echo off
REM =====================================================================
REM  Generator SKMHT lokal - peluncur Windows
REM  OCR lokal membutuhkan Pillow dari requirements.txt + Tesseract lokal.
REM  Mode AI daring (opsional) memakai endpoint OpenAI-compatible. Bila
REM  router memerlukan kunci, setel variabel lingkungan berikut SEBELUM
REM  menjalankan berkas ini (jangan tulis kunci ke dalam berkas ini):
REM      set "SKMHT_AI_API_KEY=<kunci-anda>"
REM      set "SKMHT_AI_MODEL=example-vision-model"   (opsional)
REM      set "SKMHT_AI_BASE_URL=http://localhost:8000/v1" (opsional)
REM =====================================================================
setlocal
cd /d "%~dp0"

set "PORT=8756"
if not "%~1"=="" set "PORT=%~1"

echo Menyiapkan Generator SKMHT lokal...

REM 1) Coba Python Launcher (py) lebih dulu.
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 run.py --port %PORT%
    goto :done
)

REM 2) Fallback ke python di PATH.
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python run.py --port %PORT%
    goto :done
)

echo.
echo [ERROR] Python tidak ditemukan di PATH.
echo Silakan pasang Python 3.10+ dari https://www.python.org/downloads/
echo lalu jalankan ulang berkas start.bat ini.
echo.

:done
echo.
echo Server berhenti. Tekan tombol apa saja untuk menutup jendela ini.
pause >nul
endlocal
