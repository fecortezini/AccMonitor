@echo off
rem Abre o Mercado PW numa janela propria (sem console).
rem Usa o Python que vem na pasta "python" (nao precisa instalar nada); sem ela, o Python do PC (3.11 ou mais novo).
cd /d "%~dp0"
if exist "python\pythonw.exe" (
  start "" "python\pythonw.exe" -m mercado
  exit /b
)
where pyw >nul 2>nul && (start "" pyw -3 -m mercado & exit /b)
where pythonw >nul 2>nul && (start "" pythonw -m mercado & exit /b)
echo Nao achei o Python.
echo Coloque a pasta "python" junto deste arquivo, ou instale o Python 3.11 ou mais novo (python.org).
pause
