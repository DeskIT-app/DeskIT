@echo off
rem The stranger's first run from this checkout, double-clickable: dev\stranger.py with
rem whatever follows (nothing = a fresh person, the downloads kept). Output in
rem %LOCALAPPDATA%\DeskIT-dev\stranger-launch.log, since a double-clicked console is gone
rem before it can be read.
cd /d "%~dp0.."
if not exist "%LOCALAPPDATA%\DeskIT-dev" mkdir "%LOCALAPPDATA%\DeskIT-dev"
.venv\Scripts\python.exe dev\stranger.py %* > "%LOCALAPPDATA%\DeskIT-dev\stranger-launch.log" 2>&1
