@echo off
setlocal
set "VS=C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvarsall.bat"
if not exist "%VS%" set "VS=C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat"
call "%VS%" x86 >nul || goto :err
cd /d "%~dp0"
cl /nologo /LD /O2 /EHsc /MT /Fe:d3d9.dll d3d9_cursor.cpp /link /DEF:d3d9.def /IMPLIB:d3d9_cursor.lib || goto :err
echo built: %~dp0d3d9.dll
exit /b 0
:err
echo BUILD FAILED
exit /b 1
