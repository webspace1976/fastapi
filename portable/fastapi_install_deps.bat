@echo off
:: set "PORTABLE_PY=%cd%\tools\WPy64-31180\python-3.11.8.amd64\python.exe"
set "PORTABLE_PY=%cd%\tools\WPy64-312101\python\python.exe"
set "VENV_PATH=%cd%\fastapi-main\venv"

echo Creating Virtual Environment...
"%PORTABLE_PY%" -m venv "%VENV_PATH%"

echo Activating Environment and Installing Requirements...
call "%VENV_PATH%\Scripts\activate"
pip install -r fastapi-main\requirements.txt

echo Done!
pause