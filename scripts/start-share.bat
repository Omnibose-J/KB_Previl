@echo off
REM Start the demo stack and print the public URL to share with teammates.
REM   Backend  : FastAPI on :8000  (service/app.py, opens kb.db read-only)
REM   Frontend : Vite on :5173     (proxies /api to :8000)
REM   Tunnel   : ngrok -> :5173    (PUBLIC: anyone with the URL can open it)
REM
REM Each process runs in its own window; close a window to stop that process.
REM If a port is already taken, that server exits with an error in its own
REM window - that is intentional, not a hang.

setlocal
set "ROOT=%~dp0.."

echo Starting FastAPI backend on :8000 ...
start "KB API (:8000)" /D "%ROOT%" cmd /k python -m uvicorn service.app:app --port 8000

echo Starting Vite dev server on :5173 ...
start "KB Frontend (:5173)" /D "%ROOT%\frontend\app" cmd /k npm run dev

REM Vite 6 blocks unknown Host headers, so ngrok rewrites it to localhost:5173.
echo Starting ngrok tunnel ...
start "KB Tunnel (ngrok)" cmd /k ngrok http 5173 --host-header=localhost:5173

REM Poll the local ngrok agent API until the tunnel registers its public URL.
REM The timeout must stay well above 2s: the agent API answers in ~2.0s and a
REM 2s timeout misses every single poll.
powershell -NoProfile -Command "for ($i = 0; $i -lt 20; $i++) { try { $t = (Invoke-RestMethod 'http://localhost:4040/api/tunnels' -TimeoutSec 5).tunnels } catch { $t = $null }; if ($t) { Write-Host ''; Write-Host ('  PUBLIC URL : ' + $t[0].public_url); Write-Host '  Teammates hit an ngrok warning page first - they click Visit Site.'; exit }; Start-Sleep -Seconds 1 }; Write-Host ''; Write-Host '  Public URL not ready. Check the KB Tunnel window for the error.'"

echo.
echo   Local frontend : http://localhost:5173
echo   Local API docs : http://localhost:8000/docs
echo.
echo Three windows opened. This one can be closed.
echo The public URL stops working when the tunnel window closes. Restarting has
echo so far handed back the same free static domain, so the link stays reusable.
pause
