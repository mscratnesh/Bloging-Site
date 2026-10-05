@echo off
REM Let Money Earn - one-time VM setup for the market-data tools added in October 2026:
REM Portfolio Beta (stock and mutual fund betas, hedge sizer) and the Mutual Fund Holdings Explorer.
REM
REM Run from anywhere on the build VM (the folder with app.py and LetMoneyEarn.spec):
REM     deploy\setup_data_tools.bat
REM It installs the Python packages, makes the exe bundle the Excel readers, checks the VM can
REM reach NSE, AMFI and the fund houses, and can rebuild LetMoneyEarn.exe. Safe to run again.

setlocal
cd /d "%~dp0.."
echo.
echo === Let Money Earn: setup for the market-data tools ===
echo Folder: %CD%
echo.

echo [1/6] Checking Python...
where py >nul 2>nul
if errorlevel 1 (
    echo   Python launcher "py" not found. Install Python 3 from python.org, tick "Add to PATH", then run this again.
    goto :fail
)
py --version
echo.

echo [2/6] Installing packages: pandas requests openpyxl xlrd pillow imageio-ffmpeg pyinstaller...
py -m pip install --upgrade pandas requests openpyxl xlrd pillow imageio-ffmpeg pyinstaller
if errorlevel 1 (
    echo   pip failed. Check the internet connection or proxy, then run this again.
    goto :fail
)
echo.

echo [3/6] Checking the packages import...
py deploy\check_data_tools.py imports
if errorlevel 1 goto :fail
echo.

echo [4/6] Making LetMoneyEarn.spec bundle the Excel readers (openpyxl, xlrd)...
py deploy\check_data_tools.py spec
if errorlevel 1 goto :fail
echo.

echo [5/6] Checking this VM can reach NSE, AMFI and the fund houses...
py deploy\check_data_tools.py network
if errorlevel 1 (
    echo   Continuing anyway: the site works, but the tools whose hosts failed above won't update until they're reachable.
)
echo.

echo [6/6] Rebuild LetMoneyEarn.exe now?
choice /c YN /m "Build with PyInstaller"
if errorlevel 2 goto :skipbuild
py -m PyInstaller --noconfirm LetMoneyEarn.spec
if errorlevel 1 (
    echo   The build failed; see the messages above.
    goto :fail
)
echo   Built: dist\LetMoneyEarn.exe
goto :done

:skipbuild
echo   Skipped. Build later with:  py -m PyInstaller --noconfirm LetMoneyEarn.spec

:done
echo.
echo === Setup finished ===
echo Deploy as usual (README: "Deploying an update"), and KEEP these on the VM - never overwrite them:
echo   betas.db           run log for the beta and holdings jobs
echo   data\              betas.json, mf_betas.json, mf_holdings\
echo   var\               download caches (bhavcopy, AMFI NAVs, fund holdings fallback)
echo On first start the server builds the data in the background:
echo   stock betas ~2-4 min, mutual fund betas ~4 min, fund holdings ~1 min.
echo Watch the console for "Wrote ... betas", "Wrote ... fund betas" and "Wrote ... schemes from 11 fund houses",
echo then open /portfolio-beta.html and /mf-holdings.html on the site.
echo.
pause
exit /b 0

:fail
echo.
echo === Setup stopped: fix the problem above and run this file again ===
pause
exit /b 1
