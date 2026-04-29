@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    py -3.12 main.py
)

echo.
echo [processo encerrado com o codigo %ERRORLEVEL%]
echo Pressione Enter para fechar este terminal.
pause >nul
