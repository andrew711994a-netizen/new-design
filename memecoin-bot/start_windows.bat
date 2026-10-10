@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set PY=python
where py >nul 2>nul
if %errorlevel%==0 set PY=py -3

if not exist ".venv\installed.ok" (
    echo First run: installing, this takes 1-3 minutes...
    %PY% -m venv .venv
    if errorlevel 1 goto nopython
    ".venv\Scripts\python" -m pip install --upgrade pip
    ".venv\Scripts\python" -m pip install -r requirements-live.txt
    if errorlevel 1 (
        echo The live-trading library could not be installed. Paper mode still works.
        ".venv\Scripts\python" -m pip install -r requirements.txt
        if errorlevel 1 goto failed
    )
    echo ok> ".venv\installed.ok"
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo.
    echo Created the settings file .env - Notepad opens now.
    echo Fill in PUMPPORTAL_API_KEY ^(and NTFY_TOPIC^), save, close Notepad, then come back here.
    start /wait notepad ".env"
)

:menu
echo.
echo   1 = Start the bot
echo   2 = Check setup (connection, API key, notifications)
echo   3 = Results report
echo   4 = Fee table
echo   5 = Backtest (replay the recorded market)
echo   6 = Edit settings (.env)
set CH=
set /p CH="Choose 1-6 and press Enter: "
if "%CH%"=="1" goto run
if "%CH%"=="2" ( ".venv\Scripts\python" -m memebot check & goto menu )
if "%CH%"=="3" ( ".venv\Scripts\python" -m memebot report & goto menu )
if "%CH%"=="4" ( ".venv\Scripts\python" -m memebot costs & goto menu )
if "%CH%"=="5" ( ".venv\Scripts\python" -m memebot backtest & goto menu )
if "%CH%"=="6" ( start /wait notepad ".env" & goto menu )
goto menu

:run
echo The bot is running. Close this window or press Ctrl+C to stop it.
".venv\Scripts\python" -m memebot
pause
goto menu

:nopython
echo Python was not found. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during installation.
pause
exit /b

:failed
echo Installation failed. Check your internet connection and run this file again.
pause
