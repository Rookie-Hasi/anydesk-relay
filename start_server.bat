@echo off
title AnyDesk Clone - Relay & Presence Server
cd /d "%~dp0"
echo Starting AnyDesk Clone Relay Server on port 8765...
python server\server.py
pause
