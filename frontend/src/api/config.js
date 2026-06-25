// API base URL. The production build uses '/api' (same-origin behind nginx, set
// via VITE_API_BASE_URL in .env.production); local `npm run dev` has no env var
// and falls back to the Flask dev server on :5000.
export const BACKEND_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000/api';
