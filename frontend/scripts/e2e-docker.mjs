// One-command E2E run against the docker compose stack, the way CI's e2e job runs it:
//   1. check the merged Compose files: scripts/compose_preflight.py --strict
//   2. build and start a throwaway project, pulsenet_e2e: docker-compose.yml plus
//      docker-compose.e2e.yml (fresh MySQL 8.4 + migrations, gunicorn, nginx with the
//      production build, fake LLM, mail to cypress/outbox/) on http://localhost:8080
//   3. run Cypress against it through scripts/run-cypress.mjs, forwarding any extra args
//   4. save the containers' logs to cypress/logs/compose.log, then remove the project
//      with its volumes
//
// Usage: npm run test:e2e:docker [-- --spec cypress/e2e/admin.cy.js]
// Needs Docker with the compose plugin, Python 3 (for the preflight; PYTHON=... to
// pick one) and port 8080 free. E2E_KEEP=1 leaves the stack up afterwards; remove it
// with: docker compose -p pulsenet_e2e down -v
// The project of `docker compose up` (pulsenet) is never touched.

import { spawnSync } from 'node:child_process';
import { chmodSync, closeSync, mkdirSync, openSync, rmSync } from 'node:fs';
import path from 'node:path';
import { FRONTEND_DIR, LOG_DIR, OUTBOX_DIR, PYTHON, log, portInUse, runCypress } from './e2e-lib.mjs';

const ROOT = path.resolve(FRONTEND_DIR, '..');
const PROJECT = 'pulsenet_e2e';
const E2E_DB = 'pulsenet_e2e'; // docker-compose.e2e.yml
const WEB_PORT = 8080;
const BASE_URL = `http://localhost:${WEB_PORT}`;
const READY_TIMEOUT_MS = 120_000;
const KEEP = ['1', 'true', 'yes'].includes((process.env.E2E_KEEP || '').toLowerCase());

// Every docker compose call below, and the makeAdmin task Cypress runs
// (cypress.config.js), reads the project and its files from these.
Object.assign(process.env, {
  COMPOSE_PROJECT_NAME: PROJECT,
  COMPOSE_FILE: ['docker-compose.yml', 'docker-compose.e2e.yml'].map((f) => path.join(ROOT, f)).join(path.delimiter),
  WEB_PORT: String(WEB_PORT), // over a root .env: APP_BASE_URL in the override says 8080
});

function compose(args, options = {}) {
  const result = spawnSync('docker', ['compose', ...args], { cwd: ROOT, stdio: 'inherit', ...options });
  if (result.error) throw new Error(`cannot run docker: ${result.error.message}`);
  return result.status;
}

function saveLogs() {
  mkdirSync(LOG_DIR, { recursive: true });
  const file = path.join(LOG_DIR, 'compose.log');
  const fd = openSync(file, 'w');
  try {
    compose(['logs', '--no-color', '--timestamps'], { stdio: ['ignore', fd, fd] });
  } finally {
    closeSync(fd);
  }
  return file;
}

function removeStack() {
  compose(['down', '--volumes', '--remove-orphans'], { stdio: ['ignore', 'ignore', 'inherit'] });
}

async function waitUntilReady() {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${BASE_URL}/api/test-db`);
      if (response.ok) return;
    } catch {
      // nginx not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`the stack did not answer ${BASE_URL}/api/test-db within ${READY_TIMEOUT_MS / 1000}s`);
}

async function main() {
  log('checking the Compose files (compose_preflight.py --strict)');
  const preflight = spawnSync(PYTHON, [path.join(ROOT, 'scripts', 'compose_preflight.py'), '--strict'], {
    cwd: ROOT, stdio: 'inherit',
  });
  if (preflight.error) throw new Error(`cannot run ${PYTHON}: ${preflight.error.message} (set PYTHON=...)`);
  if (preflight.status !== 0) throw new Error('compose preflight failed: nothing was started');

  removeStack(); // a run that was killed may have left its containers and data behind
  if (await portInUse(WEB_PORT)) {
    throw new Error(`port ${WEB_PORT} is already in use (docker compose up? stop it with docker compose down)`);
  }

  // The backend container writes the mails here (a bind mount), as a user of its own:
  // on Linux the folder must be writable by any user.
  rmSync(OUTBOX_DIR, { recursive: true, force: true });
  mkdirSync(OUTBOX_DIR, { recursive: true });
  chmodSync(OUTBOX_DIR, 0o777);

  log(`building and starting ${PROJECT} on ${BASE_URL}`);
  try {
    if (compose(['up', '--detach', '--build']) !== 0) throw new Error('docker compose up failed');
    await waitUntilReady();
    log('stack ready, running Cypress');
    Object.assign(process.env, {
      CYPRESS_baseUrl: BASE_URL,
      CYPRESS_apiBaseUrl: `${BASE_URL}/api`,
      E2E_COMPOSE: '1',          // makeAdmin runs manage.py in the backend container
      E2E_DB_NAME: E2E_DB,       // ...and only on this *_e2e database
      E2E_MAIL_OUTBOX: OUTBOX_DIR, // lastMail reads here
    });
    return await runCypress(process.argv.slice(2));
  } finally {
    // Also when `up` failed: the log shows which container did not start, and why.
    log(`container logs: ${path.relative(FRONTEND_DIR, saveLogs())}`);
    if (KEEP) log(`E2E_KEEP: ${PROJECT} left running (docker compose -p ${PROJECT} down -v)`);
    else removeStack();
  }
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => {
    if (!KEEP) removeStack();
    process.exit(130);
  });
}

main().then(
  (code) => {
    if (code !== 0) log('Cypress failed. Logs: frontend/cypress/logs/compose.log, screenshots: frontend/cypress/screenshots/');
    process.exit(code);
  },
  (err) => {
    console.error(`e2e: ${err.message}`);
    process.exit(1);
  },
);
