import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/ddo-builder/',
  optimizeDeps: {
    exclude: ['sql.js'], // WASM asset — must not be pre-bundled by Vite
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
