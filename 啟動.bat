@echo off
setlocal
cd /d "%~dp0"

rem 優先使用系統安裝的 Python；本機 PATH 第一個 python 可能缺少 Tcl，開不了視窗
where pyw.exe >nul 2>nul
if %errorlevel%==0 goto use_pyw

where pythonw.exe >nul 2>nul
if %errorlevel%==0 goto use_pythonw

python "filekeeper.py"
pause
exit /b 0

:use_pyw
start "" pyw.exe -3 "filekeeper.py"
exit /b 0

:use_pythonw
start "" pythonw.exe "filekeeper.py"
exit /b 0