@echo off
title ScreenShare Fullscreen Viewer

:: =====================================================================
:: CONFIGURATION
:: Configured with your ScreenShare server address
:: =====================================================================
set "ScreenShare_URL=http://192.168.31.233:5050/?room=a"

:: Allow overriding the URL via command-line arguments or drag-and-drop
if not "%~1"=="" set "ScreenShare_URL=%~1"

echo ----------------------------------------------------
echo Launching ScreenShare Viewer in Headerless Fullscreen...
echo URL: %ScreenShare_URL%
echo ----------------------------------------------------
echo.
echo NOTE: To exit the fullscreen viewer later, press Alt + F4
echo.

:: Launch Microsoft Edge in Kiosk (fullscreen/headerless) mode
start "" msedge --kiosk "%ScreenShare_URL%" --edge-kiosk-type=fullscreen

:: ---------------------------------------------------------------------
:: If you prefer Google Chrome, comment out the Edge line above (add ::) 
:: and uncomment the Chrome line below:
:: ---------------------------------------------------------------------
:: start "" chrome --kiosk "%ScreenShare_URL%"

exit