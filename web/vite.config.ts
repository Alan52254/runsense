import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
//
// The API is reached through this server under /api (VITE_API_BASE_URL=/api),
// so a phone on the same Wi-Fi -- or an HTTPS tunnel to this one port --
// gets the whole app, backend included, from a single origin.
const backend = process.env.RUNSENSE_BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    // tunnel hostnames (e.g. *.trycloudflare.com) are not known in advance
    allowedHosts: true,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  preview: {
    host: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
