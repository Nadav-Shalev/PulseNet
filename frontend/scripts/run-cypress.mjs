// Cypress launcher that clears ELECTRON_RUN_AS_NODE before starting Cypress.
//
// Why this exists: VS Code's integrated terminal / extension host runs with
// ELECTRON_RUN_AS_NODE=1 in the environment. That variable forces *any* Electron
// binary — including Cypress's bundled Electron — to behave as plain Node.js, so
// it rejects Electron's own flags and Cypress fails to launch with errors like
// "bad option: --smoke-test" or "Invalid or incompatible cached data". Deleting
// it here (child processes inherit process.env) lets Cypress launch normally,
// whether you run from VS Code, an external terminal, or CI.
//
// Usage (via package.json scripts): node scripts/run-cypress.mjs <run|open> [cypress run args]
// Extra args are parsed like the Cypress CLI, e.g. `npm run cy:run -- --spec cypress/e2e/auth_flow.cy.js`.
// scripts/e2e.mjs launches this script too, once it has started its own servers.

delete process.env.ELECTRON_RUN_AS_NODE;

const mode = process.argv[2] === 'open' ? 'open' : 'run';

async function main() {
  const cypress = (await import('cypress')).default;

  if (mode === 'open') {
    await cypress.open();
    return;
  }

  const options = await cypress.cli.parseRunArguments(['cypress', 'run', ...process.argv.slice(3)]);
  const results = await cypress.run(options);
  // cypress.run() resolves (never rejects) for both outcomes:
  //  - a run that couldn't start (config error, no specs) -> { status: 'failed' }
  //  - a completed run -> { totalFailed, ... }
  // Translate either into a non-zero exit code so `npm run cy:run` / CI fails.
  if (results.status === 'failed') {
    console.error(results.message);
    process.exit(1);
  }
  if (results.totalFailed > 0) {
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
