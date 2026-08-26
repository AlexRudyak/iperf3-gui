@echo off
REM Builds the single-file Windows executable into dist\iperf-gui.exe.
REM All bundle options live in main.spec so there is only one definition.

echo Running tests...
python -m pytest
if errorlevel 1 (
    echo.
    echo Tests failed; aborting build.
    exit /b 1
)

echo.
echo Building iperf-gui...
pyinstaller --noconfirm main.spec
if errorlevel 1 (
    echo.
    echo Build failed.
    exit /b 1
)

echo.
echo Build complete: dist\iperf-gui.exe
