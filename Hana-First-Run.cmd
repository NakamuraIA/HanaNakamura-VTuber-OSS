@echo off
setlocal
cd /d "%~dp0"
title Hana - primeira instalacao

echo.
echo ============================================================
echo   HANA - PRIMEIRA INSTALACAO
echo   Use este arquivo uma unica vez.
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 goto python_ausente

python -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 and sys.version_info.minor in range(11, 100) else 1)"
if errorlevel 1 goto python_antigo

rem A consulta usa somente a biblioteca padrao e nao altera o banco.
python -m backend.setup.database status --quiet
set "HANA_SETUP_STATUS=%errorlevel%"
if "%HANA_SETUP_STATUS%"=="0" goto ja_instalada
if "%HANA_SETUP_STATUS%"=="3" goto banco_existente
if not "%HANA_SETUP_STATUS%"=="2" goto erro_status

where node >nul 2>nul
if errorlevel 1 goto node_ausente
where npm >nul 2>nul
if errorlevel 1 goto node_ausente

echo [1/5] Preparando configuracao...
if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo       .env criado sem chaves privadas.
) else (
    echo       .env existente preservado.
)

echo [2/5] Preparando ambiente Python...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto falha
) else (
    echo       Ambiente existente reaproveitado.
)

echo [3/5] Instalando dependencias do backend...
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 goto falha

echo [4/5] Instalando dependencias do frontend...
pushd frontend
call npm install
set "HANA_NPM_STATUS=%errorlevel%"
popd
if not "%HANA_NPM_STATUS%"=="0" goto falha

echo [5/5] Criando banco e catalogos iniciais...
".venv\Scripts\python.exe" -m backend.setup.database initialize
if errorlevel 1 goto falha

echo.
echo   Instalacao concluida.
echo   1. Abra o arquivo .env e preencha uma chave de LLM.
echo   2. Depois use Hana.cmd para ligar a Hana.
echo.
pause
exit /b 0

:ja_instalada
echo   A primeira instalacao ja foi concluida.
echo   Nada foi reinstalado ou reimportado.
echo   Use Hana.cmd para ligar a Hana.
echo.
pause
exit /b 0

:banco_existente
echo   Foi encontrado um banco de uma instalacao anterior.
echo   Ele foi preservado e nenhum modelo foi importado automaticamente.
echo   Use Hana.cmd normalmente.
echo.
pause
exit /b 0

:python_ausente
echo   Python nao foi encontrado. Instale Python 3.11 ou mais novo.
goto ajuda

:python_antigo
echo   A versao do Python e antiga. Instale Python 3.11 ou mais novo.
goto ajuda

:node_ausente
echo   Node.js ou npm nao foi encontrado. Instale a versao LTS do Node.js.
goto ajuda

:erro_status
echo   Nao foi possivel consultar o estado da instalacao.
goto ajuda

:falha
echo.
echo   A instalacao parou por causa do erro mostrado acima.
echo   O banco principal nao recebe uma carga parcial de modelos.

:ajuda
echo   Consulte FIRST_RUN.md para o passo a passo e tente novamente.
echo.
pause
exit /b 1
