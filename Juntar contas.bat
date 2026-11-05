@echo off
rem Junta neste PC as contas lidas em outro PC: o arquivo contas-de-outro-pc.db, na pasta do programa.
rem Feche o Mercado PW antes. Usa o Python que vem na pasta "python"; sem ela, o Python do PC.
cd /d "%~dp0"
if exist "python\python.exe" (
  "python\python.exe" -m mercado.copiar_contas juntar %*
) else (
  py -3 -m mercado.copiar_contas juntar %*
)
pause
