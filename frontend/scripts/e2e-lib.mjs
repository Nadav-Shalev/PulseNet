// Helpers shared by the two E2E runners: scripts/e2e.mjs (local servers) and
// scripts/e2e-docker.mjs (the docker compose stack).

import { spawn } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const LOG_DIR = path.join(FRONTEND_DIR, 'cypress', 'logs');
// Mail the backend wrote during a run (MAIL_PROVIDER=file), read by cy.task('lastMail').
export const OUTBOX_DIR = path.join(FRONTEND_DIR, 'cypress', 'outbox');
export const PYTHON = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

export function log(message) {
  console.log(`e2e: ${message}`);
}

// Is anything listening on `port` (IPv6 or IPv4 loopback)? A server left running
// would otherwise answer Cypress instead of the one the run starts.
export function portInUse(port) {
  const probe = (host) => new Promise((resolve) => {
    const socket = net.connect({ host, port });
    socket.setTimeout(1000);
    socket.once('connect', () => { socket.destroy(); resolve(true); });
    socket.once('timeout', () => { socket.destroy(); resolve(false); });
    socket.once('error', () => resolve(false));
  });
  return Promise.all([probe('::1'), probe('127.0.0.1')]).then((hits) => hits.some(Boolean));
}

export function tail(file, lines = 20) {
  if (!existsSync(file)) return '';
  return readFileSync(file, 'utf8').trimEnd().split(/\r?\n/).slice(-lines).join('\n');
}

// Run Cypress through scripts/run-cypress.mjs (which clears ELECTRON_RUN_AS_NODE);
// resolves to its exit code. `args` are Cypress CLI args, e.g. ['--spec', '...'].
export function runCypress(args) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [path.join(FRONTEND_DIR, 'scripts', 'run-cypress.mjs'), 'run', ...args], {
      cwd: FRONTEND_DIR,
      stdio: 'inherit',
    });
    child.once('exit', (code) => resolve(code ?? 1));
    child.once('error', () => resolve(1));
  });
}
