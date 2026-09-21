@echo off
rem Abre o Mercado PW numa janela propria (sem console).
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 -m mercado) || (start "" pythonw -m mercado)
