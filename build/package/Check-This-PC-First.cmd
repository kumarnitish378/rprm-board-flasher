@echo off
REM ============================================================================
REM  Raphe Board Flasher - checks this PC before anything else is tried.
REM
REM  This is a .cmd on purpose. If Windows blocks the program itself, an .exe
REM  cannot tell you why - a script still can.
REM ============================================================================
setlocal
title Raphe Board Flasher - PC check

echo.
echo  ==========================================================
echo   RAPHE BOARD FLASHER - checking this computer
echo   Raphe mPhibr ^| Nitish Sharma
echo  ==========================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='SilentlyContinue';" ^
  "function Line($s,$m){ Write-Host ('  [{0}] {1}' -f $s.PadRight(4), $m) };" ^
  "Write-Host '  Windows';" ^
  "$os = Get-CimInstance Win32_OperatingSystem;" ^
  "Line 'INFO' ($os.Caption + ' (build ' + $os.BuildNumber + ')');" ^
  "Write-Host '';" ^
  "Write-Host '  Program files';" ^
  "$here = Split-Path -Parent $MyInvocation.MyCommand.Path;" ^
  "foreach ($f in @('RapheBoardFlasher.exe','_internal')) {" ^
  "  if (Test-Path (Join-Path $PWD $f)) { Line 'OK' ($f + ' found') }" ^
  "  else { Line 'STOP' ($f + ' is MISSING - extract the whole ZIP, keeping every file together') } };" ^
  "$avr = '_internal\rprm_flasher\backends\avr\tools\avrdude.exe';" ^
  "if (Test-Path $avr) { Line 'OK' 'flashing engine found' } else { Line 'STOP' 'flashing engine missing - re-extract the ZIP' };" ^
  "Write-Host '';" ^
  "Write-Host '  Windows security';" ^
  "$z = Get-Item -Path '.\RapheBoardFlasher.exe' -Stream Zone.Identifier -ErrorAction SilentlyContinue;" ^
  "if ($z) { Line 'WARN' 'files are still marked as downloaded - right-click the ZIP, Properties, tick Unblock, then extract again' }" ^
  "else { Line 'OK' 'files are not blocked by the download marker' };" ^
  "$sac = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -Name VerifiedAndReputablePolicyState -ErrorAction SilentlyContinue).VerifiedAndReputablePolicyState;" ^
  "if ($sac -eq 1) { Line 'WARN' 'Smart App Control is ON. It can refuse to run this program because it is not signed with a paid certificate.'; Line '    ' 'If the program will not start: Windows Security > App and browser control > Smart App Control settings > Off.'; Line '    ' 'Read the warning there first - switching it off cannot be undone without reinstalling Windows.' }" ^
  "elseif ($sac -eq 2) { Line 'INFO' 'Smart App Control is in evaluation mode' }" ^
  "else { Line 'OK' 'Smart App Control is not blocking programs' };" ^
  "Write-Host '';" ^
  "Write-Host '  Boards plugged in now';" ^
  "$ports = Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match '\(COM\d+\)' };" ^
  "if (-not $ports) { Line 'WARN' 'no serial ports at all - plug the board in, and install its USB driver (CH340 for most clones, FTDI for older ones)' }" ^
  "else { foreach ($p in $ports) {" ^
  "   if ($p.Name -match 'Bluetooth') { Line 'INFO' ($p.Name + '  <- Bluetooth, not a board') }" ^
  "   elseif ($p.Name -match 'Arduino|CH340|CH910|CP210|FTDI|USB-SERIAL|USB Serial') { Line 'OK' ($p.Name + '  <- looks like a board') }" ^
  "   else { Line 'INFO' $p.Name } } };" ^
  "$bad = Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 -and $_.Name -match 'USB|Serial|CH34|CP21|FTDI' };" ^
  "if ($bad) { foreach ($d in $bad) { Line 'WARN' ('driver problem: ' + $d.Name + ' - install its USB driver') } }"

echo.
echo  ==========================================================
echo.
echo   OK   = fine
echo   WARN = read it, it may still work
echo   STOP = must be fixed first
echo.
echo   Next: run RapheBoardFlasher.exe and press Self-test.
echo.
pause
endlocal
