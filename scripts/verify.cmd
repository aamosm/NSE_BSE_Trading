@echo off
rem Reproducible verification from cmd or PowerShell: uses this checkout's own venv.
"%~dp0..\.venv\Scripts\python.exe" "%~dp0verify.py" %*
