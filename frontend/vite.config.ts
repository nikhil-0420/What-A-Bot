import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  base: process.env.GITHUB_PAGES ? '/What-A-Bot/' : (process.env.VITE_BASE_PATH || '/'),
  plugins: [react()],
  server: {
    port: 3000,
  },
})
