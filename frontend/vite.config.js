import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // VITE_API_BASE_URL from the environment or frontend/.env*. The production build sets
  // a relative /api (.env.production), which resolves against the local backend here:
  // only the dev server uses this proxy.
  const { VITE_API_BASE_URL } = loadEnv(mode, '.', 'VITE_')
  const apiOrigin = new URL(VITE_API_BASE_URL || '/api', 'http://localhost:5000').origin
  return {
    plugins: [react()],
    // Uploaded images come back as relative /uploads/<file> URLs. In production the
    // page and the backend share one origin (nginx proxies /uploads); in development
    // the dev server forwards them to the backend the same way.
    server: { proxy: { '/uploads': apiOrigin } },
  }
})
