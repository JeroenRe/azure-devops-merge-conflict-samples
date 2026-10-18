@echo off
setlocal enableextensions

rem Build script for the sample solution.
set CONFIG=Release
set OUTDIR=bin\%CONFIG%

if not exist "%OUTDIR%" mkdir "%OUTDIR%"

echo Building %CONFIG% ...
msbuild Sample.sln /p:Configuration=%CONFIG% /m
if errorlevel 1 goto :failed

echo Copying output ...
xcopy /Y /Q "src\Sample\bin\%CONFIG%\*.*" "%OUTDIR%\" >nul
echo Done.
exit /b 0

:failed
echo Build failed.
exit /b 1
