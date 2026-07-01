// When served by FastAPI (production/tunnel): use relative path — same origin, no CORS.
// When running Vite dev server locally: proxy to port 8000.
const isDev = window.location.port === '5173';
export const API_BASE_URL = isDev
  ? `http://${window.location.hostname}:8000/api`
  : '/api';
