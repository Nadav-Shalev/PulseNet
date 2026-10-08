// One-command E2E run against a throwaway stack, so Cypress never touches the dev DB:
//   1. rebuild the `pulsenet_e2e` database from the migrations (backend/migrate.py --reset)
//   2. start the backend on it, with the fake LLM and file mail providers
//   3. start the Vite dev server
//   4. run Cypress through scripts/run-cypress.mjs, forwarding any extra args
//   5. stop both servers and exit with Cypress's result
//
// Usage: npm run test:e2e [-- --spec cypress/e2e/auth_flow.cy.js]
// Needs MySQL running with the credentials in backend/.env, and ports 5000 / 5173 free.
// Server output goes to cypress/logs/{backend,vite}.log (git-ignored).
// Env overrides: PYTHON (interpreter, default python / python3), E2E_BACKEND_HOST (default ::1).

import { spawn, spawnSync } from 'node:child_process';
import { closeSync, existsSync, mkdirSync, openSync, readFileSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BACKEND_DIR = path.resolve(FRONTEND_DIR, '..', 'backend');
const LOG_DIR = path.join(FRONTEND_DIR, 'cypress', 'logs');

const PYTHON = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const E2E_DB = 'pulsenet_e2e';
// Same IPv6 loopback the dev server binds in app.py: on Windows the browser's
// `localhost` resolves to ::1 first (see the note at the bottom of app.py).
const BACKEND_HOST = process.env.E2E_BACKEND_HOST || '::1';
const BACKEND_PORT = 5000;
const VITE_PORT = 5173;
const API_BASE_URL = `http://localhost:${BACKEND_PORT}/api`; // what the app and cypress.config.js use
const READY_TIMEOUT_MS = 60_000;

const servers = [];

function log(message) {
  console.log(`e2e: ${message}`);
}

// Is anything listening on `port` (IPv6 or IPv4 loopback)? A dev server left running
// would otherwise serve Cypress from the dev database.
function portInUse(port) {
  const probe = (host) => new Promise((resolve) => {
    const socket = net.connect({ host, port });
    socket.setTimeout(1000);
    socket.once('connect', () => { socket.destroy(); resolve(true); });
    socket.once('timeout', () => { socket.destroy(); resolve(false); });
    socket.once('error', () => resolve(false));
  });
  return Promise.all([probe('::1'), probe('127.0.0.1')]).then((hits) => hits.some(Boolean));
}

function tail(file, lines = 20) {
  if (!existsSync(file)) return '';
  return readFileSync(file, 'utf8').trimEnd().split(/\r?\n/).slice(-lines).join('\n');
}

// Start a long-running server with its output in cypress/logs/<name>.log.
function startServer(name, command, args, options) {
  const logFile = path.join(LOG_DIR, `${name}.log`);
  const fd = openSync(logFile, 'w');
  const child = spawn(command, args, { ...options, stdio: ['ignore', fd, fd] });
  closeSync(fd); // the child holds its own copy
  const server = { name, child, logFile, exited: null };
  child.once('exit', (code) => { server.exited = code ?? 'signal'; });
  child.once('error', (err) => { server.exited = err.message; });
  servers.push(server);
  return server;
}

function stopServers() {
  for (const { child } of servers) {
    if (child.exitCode === null && !child.killed) child.kill();
  }
}

// Poll `url` until `isReady(response)` is true; fail fast if the server process exits.
async function waitUntilReady(server, url, isReady) {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (server.exited !== null) {
      throw new Error(`${server.name} exited (${server.exited}) before it was ready:\n${tail(server.logFile)}`);
    }
    let response = null;
    try {
      response = await fetch(url);
    } catch {
      // not listening yet
    }
    if (response && await isReady(response)) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${server.name} not ready after ${READY_TIMEOUT_MS / 1000}s at ${url}:\n${tail(server.logFile)}`);
}

function runNode(args) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, args, { cwd: FRONTEND_DIR, stdio: 'inherit' });
    child.once('exit', (code) => resolve(code ?? 1));
    child.once('error', () => resolve(1));
  });
}

async function main() {
  for (const port of [BACKEND_PORT, VITE_PORT]) {
    if (await portInUse(port)) {
      throw new Error(`port ${port} is already in use. Stop the dev server first: the E2E run starts its own, on ${E2E_DB}.`);
    }
  }

  log(`rebuilding ${E2E_DB}`);
  const migrate = spawnSync(PYTHON, [path.join(BACKEND_DIR, 'migrate.py'), '--db', E2E_DB, '--reset'], {
    stdio: 'inherit',
  });
  if (migrate.error) throw new Error(`cannot run ${PYTHON}: ${migrate.error.message} (set PYTHON=...)`);
  if (migrate.status !== 0) throw new Error(`migrate.py failed (exit ${migrate.status})`);

  mkdirSync(LOG_DIR, { recursive: true });
  log(`starting backend on [${BACKEND_HOST}]:${BACKEND_PORT} and Vite on :${VITE_PORT} (logs: cypress/logs/)`);
  const backend = startServer('backend', PYTHON, [
    '-m', 'flask', '--app', 'app', 'run', '--host', BACKEND_HOST, '--port', String(BACKEND_PORT),
  ], {
    cwd: BACKEND_DIR,
    env: {
      ...process.env,
      DB_NAME: E2E_DB, // wins over backend/.env: load_dotenv never overrides real env vars
      LLM_PROVIDER: 'fake', // backend/llm answers offline and the same way every time: no key, no quota
      // Moderation asks the LLM about every post and comment the specs create (the
      // fake's echo is never cached), so the default 100 calls a day is too tight.
      LLM_DAILY_LIMIT: '1000',
      MAIL_PROVIDER: 'file', // mails written to disk, never sent (mail service, later sessions)
      PYTHONUNBUFFERED: '1',
    },
  });
  const vite = startServer('vite', process.execPath, [
    path.join(FRONTEND_DIR, 'node_modules', 'vite', 'bin', 'vite.js'), '--port', String(VITE_PORT), '--strictPort',
  ], {
    cwd: FRONTEND_DIR,
    env: { ...process.env, VITE_API_BASE_URL: API_BASE_URL }, // ignore any frontend/.env override
  });

  const backendHost = BACKEND_HOST.includes(':') ? `[${BACKEND_HOST}]` : BACKEND_HOST;
  await Promise.all([
    // /api/test-db answers 500 when the DB is unreachable; that will not fix itself.
    waitUntilReady(backend, `http://${backendHost}:${BACKEND_PORT}/api/test-db`, async (response) => {
      if (response.status === 500) throw new Error(`backend cannot reach the DB: ${await response.text()}`);
      return response.ok;
    }),
    waitUntilReady(vite, `http://localhost:${VITE_PORT}/`, (response) => response.ok),
  ]);
  log('servers ready, running Cypress');

  return runNode([path.join(FRONTEND_DIR, 'scripts', 'run-cypress.mjs'), 'run', ...process.argv.slice(2)]);
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => {
    stopServers();
    process.exit(130);
  });
}

main().then(
  (code) => {
    stopServers();
    if (code !== 0) log('Cypress failed. Server logs: frontend/cypress/logs/');
    process.exit(code);
  },
  (err) => {
    console.error(`e2e: ${err.message}`);
    stopServers();
    process.exit(1);
  },
);
