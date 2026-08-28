@echo off
rem ============================================================
rem  Desliga a Hana: fecha a janela e o backend escondido.
rem
rem  Necessario porque o Hana.cmd sobe o backend com pythonw (sem console).
rem  Fechar a janela do app NAO mata ele — fica ali segurando a porta 8042 e a
rem  placa de som.
rem
rem  Pede pro backend se encerrar (POST /api/system/shutdown) em vez de matar o
rem  processo. Motivo: `taskkill` falha quando o processo foi aberto por outra
rem  sessao — foi exatamente o que acontecia antes. Pedindo, nao existe questao
rem  de permissao, e ele ainda fecha o bot do Discord e a voz direito.
rem ============================================================

title Desligando a Hana

echo Fechando a janela do app...
taskkill /f /im hana-control-center.exe >nul 2>&1

echo Pedindo pro backend desligar...
curl -s -m 5 -X POST http://127.0.0.1:8042/api/system/shutdown >nul 2>&1

rem Da 4 segundos pro shutdown gracioso terminar.
set /a espera=0
:aguardar
ping -n 2 127.0.0.1 >nul
curl -s -o nul -m 2 http://127.0.0.1:8042/api/health 2>nul
if not %errorlevel%==0 goto pronto
set /a espera+=1
if %espera% lss 4 goto aguardar

rem --- plano B: ele nao saiu sozinho, entao mata ---
echo Nao saiu sozinho. Encerrando na forca...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8042" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%p >nul 2>&1
)
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

ping -n 3 127.0.0.1 >nul
curl -s -o nul -m 2 http://127.0.0.1:8042/api/health 2>nul
if %errorlevel%==0 (
    echo.
    echo   Ainda tem algo na porta 8042.
    echo   Provavel: o backend esta rodando com outro usuario ou como admin.
    echo   Nesse caso, feche pelo terminal onde voce o iniciou.
    echo.
    pause
    exit /b 1
)

:pronto
echo Hana desligada.
ping -n 2 127.0.0.1 >nul
exit /b 0
