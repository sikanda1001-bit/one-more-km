@echo off
REM SikandX local Android setup — needs Node.js + Android Studio installed.
cd /d "%~dp0"
call npm install
call npx cap add android
call npx cap sync android
echo.
echo Done. Opening Android Studio — use Build ^> Build APK(s).
call npx cap open android
