import { spawnSync } from 'node:child_process'
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
        // make-admin. Only on the database scripts/e2e.mjs rebuilt for this run
        // (E2E_DB_NAME, *_e2e), so a spec can never promote anyone anywhere else.
        //   cy.task('makeAdmin', user.username)
        makeAdmin(username) {
          const db = process.env.E2E_DB_NAME || ''
          if (!/_e2e$/.test(db)) {
            throw new Error(`makeAdmin runs only on an *_e2e database (E2E_DB_NAME=${db || 'unset'}): use npm run test:e2e`)
          }
          const result = spawnSync(PYTHON, [path.join(BACKEND_DIR, 'manage.py'), 'make-admin', username], {
            env: { ...process.env, DB_NAME: db },
            encoding: 'utf8',
          })
          if (result.status !== 0) {
            throw new Error(`make-admin failed (exit ${result.status}): ${result.stderr || result.stdout || result.error}`)
          }
          return null
        },
      })
    },
  },
})
