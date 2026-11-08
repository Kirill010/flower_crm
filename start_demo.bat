@echo off
rem Demo mode: fictional data in a separate demo.db, working data is not touched.
cd /d "%~dp0"
start "" pythonw crm.py --demo
