# StudyFlow Frontend

Next.js App Router + TypeScript + Tailwind CSS.

See [the project README](../README.md) for setup and verification instructions.

Run npm ci, then npm run dev -- --hostname 127.0.0.1.
Open http://localhost:3000.

Phase 7 pages require the FastAPI backend on port 8000. The default same-origin
`/api` proxy keeps credentials on the backend. For another upstream, copy the
public/server URL placeholders from `.env.example` to a new `.env.local` without
overwriting existing configuration, then restart/rebuild.

Do not place Canvas or LLM credentials in this directory or in public variables.

Verification: `npm test`, `npm run typecheck`, `npm run lint`, `npm run build`.
The test fixtures live only under `tests/` and are not imported by the app.

See [Phase 7 interface and verification](../docs/interface.md) for routes,
safe PDF links and scoped sync. The [V1 release verification](../docs/v1-release.md)
passed with current production knowledge, real source links and answer interactions.
