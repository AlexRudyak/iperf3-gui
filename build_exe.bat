@echo off
echo Building iperf_gui...
pyinstaller --noconfirm --onefile --windowed --icon "iperf_gui\assets\app_icon.ico" --add-data "iperf_gui\assets\app_icon.ico;assets" --add-data "iperf_gui\assets\style.qss;assets" --add-data "iperf3.exe;." --add-data "cygwin1.dll;." "main.py"
echo Build complete!
pause
