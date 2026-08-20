@echo off
setlocal enabledelayedexpansion

REM ------------------------------------------------------------
REM Script de compilación para generar start.exe sin consola
REM ------------------------------------------------------------

set PROJECT_DIR=%~dp0
pushd %PROJECT_DIR%

REM Detectar intérprete de Python preferido (venv si existe)
set PYTHON_EXE=python
if exist "%PROJECT_DIR%venv\Scripts\python.exe" (
	set PYTHON_EXE=%PROJECT_DIR%venv\Scripts\python.exe
)

echo Instalando dependencias requeridas...
"%PYTHON_EXE%" -m pip install --upgrade pip >nul
"%PYTHON_EXE%" -m pip install -r requirements.txt >nul

echo Limpiando artefactos previos...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist start.spec del /q start.spec

echo Generando ejecutable (este paso puede tardar)...
"%PYTHON_EXE%" -m PyInstaller ^
	--noconfirm ^
	--clean ^
	--noconsole ^
	--onefile ^
	--icon img/icon.ico ^
	--add-data "templates;templates" ^
	--add-data "static;static" ^
	--add-data "src;src" ^
	--add-data "config;config" ^
	--hidden-import "src.database" ^
	--hidden-import "config.settings" ^
	start.py

if errorlevel 1 (
	echo.
	echo ❌ Ocurrió un error durante la compilación.
	pause
	popd
	exit /b 1
)

echo.
echo ✅ Ejecución completada. Ejecutable disponible en dist\start.exe
pause

popd
