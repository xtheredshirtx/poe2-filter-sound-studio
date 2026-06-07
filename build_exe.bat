@echo off

:: Check if PyInstaller is installed
pyinstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller is not installed. Please install it using 'pip install pyinstaller'.
    pause
    exit /b
)

:: Set the version number (auto-increment)
set /p version_number=<version.txt
set /a new_version=version_number+1
echo %new_version% >version.txt
echo Building version %new_version%

:: Find the first .ico file in the current directory
for %%i in (*.ico) do set icon_file=%%i
if not defined icon_file (
    echo Icon file not found! Please ensure a .ico file is in the current directory.
    pause
    exit /b
)

echo Using icon file: "%icon_file%"

:: Create output directory if it doesn't exist
if not exist "dist\builds" (
    mkdir "dist\builds"
)

:: Check if FFmpeg executable exists in the expected location
set "ffmpeg_path=ffmpeg\bin\ffmpeg.exe"
if exist %ffmpeg_path% (
    echo FFmpeg found. Including it in the build.
    set add_data=--add-data "%ffmpeg_path%;ffmpeg/bin"
) else (
    echo FFmpeg not found. Building without FFmpeg.
    set "add_data="
)

:: Economy Tier Visual Preset: bundle its read-only data + JSON schemas so the
:: frozen build can resolve them via sys._MEIPASS.
set etvp_data=--add-data "data\economy_tiers\poe2_0_5_tiers.json;data/economy_tiers" --add-data "data\color_templates\economy_tier_templates.json;data/color_templates" --add-data "economy_tier\schemas;economy_tier/schemas"

:: Run PyInstaller with custom output directory, icon, versioning, and conditional FFmpeg inclusion
pyinstaller --onefile --windowed --icon="%icon_file%" --name "App_v%new_version%" --distpath "dist\builds" %add_data% %etvp_data% --hidden-import jsonschema main.py

:: Check if the build was successful
if %errorlevel% neq 0 (
    echo Build failed! Check the output for errors.
    pause
    exit /b
)

echo Build successful! Executable located in dist\builds folder.
pause
