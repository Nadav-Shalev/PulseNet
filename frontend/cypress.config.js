import { spawnSync } from 'node:child_process'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'cypress'

const BACKEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'backend')
const PYTHON = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3')

export default defineConfig({
  e2e: {
    baseUrl: 'http://localhost:5173',
    specPattern: 'cypress/e2e/**/*.cy.{js,jsx,ts,tsx}',
    supportFile: 'cypress/support/e2e.js',
    env: {
      apiBaseUrl: 'http://localhost:5000/api',
    },
    setupNodeEvents(on) {
      on('task', {
        // Make a user an admin the only way the app allows: backend/manage.py
        // make-admin. Only on the database the runner rebuilt for this run
        // (E2E_DB_NAME, *_e2e), so a spec can never promote anyone anywhere else.
        // scripts/e2e.mjs runs the backend here; scripts/e2e-docker.mjs in docker
        // compose (E2E_COMPOSE), so manage.py runs in the backend container there
        // (the project comes from COMPOSE_PROJECT_NAME / COMPOSE_FILE).
        //   cy.task('makeAdmin', user.username)
        makeAdmin(username) {
          const db = process.env.E2E_DB_NAME || ''
          if (!/_e2e$/.test(db)) {
            throw new Error(`makeAdmin runs only on an *_e2e database (E2E_DB_NAME=${db || 'unset'}): use npm run test:e2e`)
          }
          const [command, args] = process.env.E2E_COMPOSE
            ? ['docker', ['compose', 'exec', '-T', '-e', `DB_NAME=${db}`, 'backend', 'python', 'manage.py', 'make-admin', username]]
            : [PYTHON, [path.join(BACKEND_DIR, 'manage.py'), 'make-admin', username]]
          const result = spawnSync(command, args, {
            env: { ...process.env, DB_NAME: db },
            encoding: 'utf8',
          })
          if (result.status !== 0) {
            throw new Error(`make-admin failed (exit ${result.status}): ${result.stderr || result.stdout || result.error}`)
          }
          return null
        },
        // One agent turn for `username`, the way the timer runs it: backend/manage.py
        // agent-tick --agent. Only on the run's *_e2e database, like makeAdmin, and
        // with the LLM off (LLM_PROVIDER empty), so the only skill it can run is
        // like_or_follow: no model is ever called and the turn is a like or a follow.
        // Resolves to manage.py's output, whose last line names the turn:
        //   "manage: agent rex_ai, skill like_or_follow: liked (like 12)".
        //   cy.task('agentTick', 'rex_ai').then((out) => ...)
        agentTick(username) {
          const db = process.env.E2E_DB_NAME || ''
          if (!/_e2e$/.test(db)) {
            throw new Error(`agentTick runs only on an *_e2e database (E2E_DB_NAME=${db || 'unset'}): use npm run test:e2e`)
          }
          const tick = ['manage.py', 'agent-tick', '--agent', username]
          const [command, args] = process.env.E2E_COMPOSE
            ? ['docker', ['compose', 'exec', '-T', '-e', `DB_NAME=${db}`, '-e', 'AGENTS_ENABLED=1',
                '-e', 'LLM_PROVIDER=', 'backend', 'python', ...tick]]
            : [PYTHON, [path.join(BACKEND_DIR, tick[0]), ...tick.slice(1)]]
          const result = spawnSync(command, args, {
            env: { ...process.env, DB_NAME: db, AGENTS_ENABLED: '1', LLM_PROVIDER: '' },
            encoding: 'utf8',
          })
          if (result.status !== 0) {
            throw new Error(`agent-tick failed (exit ${result.status}): ${result.stderr || result.stdout || result.error}`)
          }
          return result.stdout
        },
        // The newest mail the backend wrote to `to` (MAIL_PROVIDER=file, into the
        // outbox scripts/e2e.mjs empties for each run), or null when there is none.
        //   cy.task('lastMail', user.email).then((mail) => mail.text)
        lastMail(to) {
          const dir = process.env.E2E_MAIL_OUTBOX || ''
          if (!dir) {
            throw new Error('lastMail reads the outbox of an E2E run (E2E_MAIL_OUTBOX unset): use npm run test:e2e')
          }
          if (!existsSync(dir)) return null
          // File names start with the UTC send time, so sorted means oldest first.
          const mails = readdirSync(dir)
            .filter((name) => name.endsWith('.json'))
            .sort()
            .map((name) => JSON.parse(readFileSync(path.join(dir, name), 'utf8')))
            .filter((mail) => mail.to === to)
          return mails.length ? mails[mails.length - 1] : null
        },
      })
    },
  },
})
