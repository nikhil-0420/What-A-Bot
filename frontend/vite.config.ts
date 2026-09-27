import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  base: '/What-A-Bot/',
  plugins: [react()],
  server: {
    port: 3000,
  },
})
