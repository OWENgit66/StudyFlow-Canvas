# StudyFlow Windows launcher

The launcher is a local convenience layer for the existing V1 application. It adds no Electron, EXE packaging, database changes, AI requests or Canvas sync.

## First-time setup

Install the existing dependencies from README: Python 3.12 environment at `backend/.venv`, backend requirements, Node.js on PATH and `npm ci` in `frontend`. Run `npm run build` in `frontend` once. Existing backend/root `.env` loading is unchanged; keys never belong in launcher scripts or shortcuts. No administrator rights are normally required.

Double-click `launcher/StudyFlow.cmd`. A short status window reports readiness, hidden server processes continue running, and the default browser opens `http://localhost:3000`. Closing the browser does not stop the servers. Double-click `launcher/Stop StudyFlow.cmd` to stop launcher-owned servers; close the browser tab separately if desired.

## Startup and ownership

- Backend: `backend/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log`, working directory `backend`. Reload is off; access logging is disabled to avoid recording request URLs.
- Frontend: the installed Node executable runs `frontend/node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3000`, working directory `frontend`. This is the existing npm `start` script's Next.js command, called directly to avoid npm/cmd wrapper ownership ambiguity.
- A mutex keyed by project root serializes simultaneous start/stop requests. Existing listeners and owned starting processes are checked before launching another process.
- Backend readiness requires HTTP 200, health status `ok` and the StudyFlow OpenAPI title. Frontend readiness requires HTTP 200 and the StudyFlow/Next.js page. A foreign or unhealthy listener is never killed or duplicated; readiness eventually fails with a port/log message.
- Servers are hidden with Windows `Start-Process`. Friendly launcher output stays visible; `.cmd` wrappers pause on errors. Both readiness checks are bounded (60 seconds per service by default).
- `.runtime/backend.json` and `.runtime/frontend.json` record project root, role, PID, creation time, executable and command line. Stop requires matching identity, not just a PID. Verified process trees are terminated with `taskkill /PID ... /T /F`, including the Python venv redirector child. There is no process-name-wide termination.
- Existing manually started servers can be reused, but are not adopted into launcher ownership. Stop leaves them running. Start errors roll back only servers started by that invocation, leaving pre-existing ones alone.

Scripts resolve the root relative to their own location and handle spaces/non-ASCII paths. There is no personal absolute path in source. After moving the project, stop the old instance first, update any shortcut, and rebuild/recreate installed dependencies if their runtime paths require it. Do not copy live `.runtime` records to a second installation.

## Logs and diagnostics

`logs/backend.log`, `logs/backend.error.log`, `logs/frontend.log`, `logs/frontend.error.log` receive server stdout/stderr. They are replaced on the next fresh start of that service; `logs/launcher.log` appends friendly statuses. Launcher logs never dump settings, environment variables or Authorization headers. Existing services retain their own error sanitization. All logs and runtime files are ignored by Git.

Common failures:

- Missing virtual environment: follow backend setup in README.
- Missing Node/dependencies: install Node and run `npm ci` in frontend.
- Missing production build: run `npm run build` in frontend before launching.
- Occupied port or unhealthy server: inspect the runtime error log; stop the other application yourself or stop a manually launched StudyFlow in its original terminal. The launcher will not kill it.
- A corporate policy blocks PowerShell scripts: the wrapper uses a process-only execution-policy override, without changing machine/user policy. It cannot override enforced organization policy.

Optional terminal verification without opening a browser:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File launcher/start-studyflow.ps1 -NoBrowser
powershell.exe -NoProfile -ExecutionPolicy Bypass -File launcher/stop-studyflow.ps1
```

Stopping uses forced process-tree termination: wait for any sync/knowledge operation to finish first. It is not an application-level graceful job cancellation mechanism. If a wrapper crashes and loses its process tree, unverified/orphaned processes are deliberately not terminated by guessing ownership. Logs are local and not automatically rotated by size.

## Desktop shortcut

1. Right-click `launcher/StudyFlow.cmd`; on Windows 11 select **Show more options**, then **Send to → Desktop (create shortcut)**. Alternatively create a shortcut manually with that file as its target.
2. Rename the shortcut **StudyFlow**. Its working directory is not significant because the script resolves its own project root.
3. Under **Properties → Shortcut → Change Icon**, select a local `.ico` if desired. No credentials belong in shortcut arguments.
4. Use **Pin to Start** or **Pin to taskbar** if your Windows version offers it; direct `.cmd` pinning is not supported by every version. A desktop shortcut remains sufficient.
5. Optionally create a separate **Stop StudyFlow** shortcut using the stop `.cmd` file.

No desktop files, shortcuts, startup tasks or system-wide preferences are created automatically.

## Verification

Run the opt-in real-process test with ports 8000 and 3000 free:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File launcher/test-launcher.ps1
```

It tests concurrent cold starts, health/frontend readiness, repeated starts retaining the same PIDs, stale PID protection, owned process-tree shutdown, survival of independent Python/Node workloads, and restart. It stops its servers and test workloads afterward. It uses the normal local application/database and only reads health, OpenAPI and frontend endpoints; no sync or paid API calls occur.

Verified on Windows with Windows PowerShell 5.1 (2026-09-23): all lifecycle and concurrent-start checks passed. Missing backend/frontend prerequisites produced friendly errors and exit code 1; the latter preserved an already-running backend. Manual-server reuse/stop protection passed. The actual start `.cmd` opened the default browser (Edge) on StudyFlow; `/health` and the frontend returned HTTP 200. A concurrent logging race found during testing was fixed by taking the mutex before writing shared launcher logs.

Regression results: backend **458 passed, 1 skipped** (existing Windows symlink privilege case); frontend **20 passed**; typecheck, lint and production build passed. Configured-secret comparisons found no key/token values in launcher files or runtime logs. No real Canvas or LLM calls were made.
