@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM Pythonの存在確認
where python >nul 2>nul
if errorlevel 1 (
    echo [エラー] Pythonがインストールされていません。
    echo https://www.python.org/ からインストールしてください。
    pause
    exit /b 1
)

REM スクリプト存在確認
if not exist "MangaCompressor.py" (
    echo [エラー] MangaCompressor.py が見つかりません。
    pause
    exit /b 1
)

REM 起動 (pythonw でコンソール非表示)
start "" pythonw "MangaCompressor.py"
exit /b 0
