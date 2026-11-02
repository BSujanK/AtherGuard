import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const API_ORIGIN = process.env.AETHERGUARD_API_ORIGIN ?? 'http://127.0.0.1:8790'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: API_ORIGIN, changeOrigin: true },
      '/health': { target: API_ORIGIN, changeOrigin: true },
      // The gauge trust JSON route; anchored so the client route /sensors-sources stays with the SPA.
      '^/sensors(?:[?]|$)': { target: API_ORIGIN, changeOrigin: true },
      // The per-cell explanation JSON (`/risk`, `/risk/cell/{id}`); no client route starts with /risk.
      '^/risk(?:/|[?]|$)': { target: API_ORIGIN, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1200,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'three', test: /node_modules[\/](three|postprocessing)[\/]/, priority: 30 },
            { name: 'echarts', test: /node_modules[\/](echarts|zrender)[\/]/, priority: 20 },
          ],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
})
