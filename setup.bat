@echo off
echo ===================================================
echo Ticket Booker Bot Setup
echo ===================================================

echo Installing Python dependencies...
pip install -r requirements.txt

echo.
echo Installing Playwright browsers...
playwright install chromium
playwright install-deps chromium

echo.
echo ===================================================
echo Setup complete! You can now run the bot using:
echo python main.py
echo ===================================================
pause
