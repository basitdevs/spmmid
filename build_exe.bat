@echo off
rem Builds submission\SPMS.exe. Requires: pip install flask pyinstaller
python -m PyInstaller --noconfirm --onefile --name SPMS --distpath submission --workpath "%TEMP%\spms_build" --specpath "%TEMP%\spms_build" --add-data "%CD%\spms\templates;spms\templates" --add-data "%CD%\spms\static;spms\static" --add-data "%CD%\spms\schema.sql;spms" run.py
