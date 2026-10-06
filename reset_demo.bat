@echo off
cd /d "%~dp0"
echo Creating fresh demo data and checking all three demo days (about 2-3 minutes)...
python seed_demo_db.py
python pipeline.py
echo.
echo Ready. Double-click start_demo.bat to open the portal.
pause
