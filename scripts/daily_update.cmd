@echo off
rem MarketLab evening update (research workspace): official NSE files -> panel -> ranking -> score past rankings.
rem No broker access, no orders. Scheduled by Windows Task Scheduler on weekdays after the close:
rem   schtasks /Create /TN "MarketLab daily update" /TR "\"%~dp0daily_update.cmd\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 18:45
rem Remove with:  schtasks /Delete /TN "MarketLab daily update" /F
cd /d "%~dp0.."
set PYTHONPATH=src
echo ==== %DATE% %TIME% ==== >> data\research\daily-scheduled.log
".venv\Scripts\python.exe" -u scripts\daily_update.py --private-dir data\research\private --market-dir data\research\market >> data\research\daily-scheduled.log 2>&1
