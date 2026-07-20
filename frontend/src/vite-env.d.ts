/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute backend URL (e.g. https://taskpilot-backend.up.railway.app).
   *  Leave unset for same-origin deploys (e.g. docker-compose's nginx proxy),
   *  where relative "/api/..." paths already reach the backend. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
