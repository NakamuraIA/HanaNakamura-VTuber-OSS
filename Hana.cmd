@echo off
rem ============================================================
rem  Liga a Hana: backend escondido + a janela do app.
rem
rem  Clique duas vezes neste arquivo. Sem terminal, sem comando.
rem  (Crie um atalho na area de trabalho: botao direito -> Enviar para
rem   -> Area de trabalho.)
rem ============================================================

cd /d "%~dp0"
title Hana

rem --- ja esta rodando? ---
rem Sem esta checagem, o segundo clique sobe um backend novo, a porta 8042
rem ja esta ocupada, e ele morre em silencio deixando so a tela branca.
curl -s -o nul -m 2 http://127.0.0.1:8042/api/health 2>nul
if %errorlevel%==0 (
    echo Backend ja esta de pe. Abrindo so a janela...
    goto abrir
)

rem --- instalacao inicial separada do uso diario ---
if not exist "runtime\hana_memory.sqlite3" (
    echo.
    echo   A primeira instalacao ainda nao foi feita.
    echo   Execute Hana-First-Run.cmd uma unica vez.
    echo.
    pause
    exit /b 1
)

rem --- primeira vez? ---
if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo   O ambiente Python ainda nao foi criado.
    echo   Rode uma vez, nesta pasta:
    echo.
    echo       python -m venv .venv
    echo       .venv\Scripts\activate
    echo       pip install -r backend\requirements.txt
    echo.
    pause
    exit /b 1
)

rem --- sobe o backend sem janela preta ---
rem pythonw.exe = python sem console. `start ""` solta o processo, entao
rem fechar este .cmd nao mata a Hana.
echo Ligando a Hana...
start "" ".venv\Scripts\pythonw.exe" -m uvicorn backend.main:app --port 8042 --ws-max-size 67108864

rem --- espera ficar de pe (ate 30s) ---
rem O app abrir antes do backend responder = tela branca e ela achando que
rem quebrou. Melhor esperar aqui.
set /a tentativas=0
:esperar
ping -n 2 127.0.0.1 >nul
curl -s -o nul -m 2 http://127.0.0.1:8042/api/health 2>nul
if %errorlevel%==0 goto abrir
set /a tentativas+=1
if %tentativas% lss 30 goto esperar

echo.
echo   O backend nao subiu em 30 segundos.
echo   Para ver o erro, rode na mao:
echo       .venv\Scripts\python.exe -m uvicorn backend.main:app --port 8042
echo.
pause
exit /b 1

:abrir
set "APP=frontend\src-tauri\target\release\hana-control-center.exe"
if exist "%APP%" (
    start "" "%APP%"
) else (
    rem Sem o app compilado, abre no navegador mesmo — o backend ja esta de pe.
    echo App nao compilado. Para gerar:  cd frontend ^&^& npm run tauri build
    echo Abrindo pelo navegador...
    start "" http://127.0.0.1:8042/docs
)
exit /b 0
