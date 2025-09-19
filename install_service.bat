REM @echo off
REM REM ============================
REM REM INSTALLATION DU SERVICE WINDOWS POUR OdooRealtime
REM REM ============================
REM 
REM REM === Configuration du service ===
REM set SERVICE_NAME=OdooRealtimeService
REM set PYTHON_PATH=set PYTHON_PATH=C:\Users\user-eatnr-226\AppData\Local\Programs\Python\Python313\python.exe
REM set SCRIPT_PATH=C:\ProjetODOOELK\main.py
REM set WORKING_DIR=C:\ProjetODOOELK
REM set NSSM_PATH=C:\nssm\nssm-2.24\win64\nssm.exe
REM set LOG_DIR=C:\ProjetODOOELK\logs
REM 
REM REM === Création du dossier log si inexistant ===
REM if not exist "%LOG_DIR%" (
REM     mkdir "%LOG_DIR%"
REM )
REM 
REM REM === Installer le service ===
REM "%NSSM_PATH%" install %SERVICE_NAME% "%PYTHON_PATH%" "%SCRIPT_PATH%"
REM "%NSSM_PATH%" set %SERVICE_NAME% AppDirectory "%WORKING_DIR%"
REM "%NSSM_PATH%" set %SERVICE_NAME% AppStdout "%LOG_DIR%\stdout.log"
REM "%NSSM_PATH%" set %SERVICE_NAME% AppStderr "%LOG_DIR%\stderr.log"
REM "%NSSM_PATH%" set %SERVICE_NAME% AppRotateFiles 1
REM 
REM REM === Démarrer le service ===
REM "%NSSM_PATH%" start %SERVICE_NAME%
REM 
REM echo.
REM echo ✅ Service %SERVICE_NAME% installé et démarré avec succès !
REM pause