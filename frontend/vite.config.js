import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true   // exposes on 0.0.0.0 → accessible from phone on same WiFi
  }
})
