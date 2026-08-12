/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
    // Found via a real cross-test leak: a stray async call from a PREVIOUS
    // test's unmounted component landed in the NEXT test's vi.spyOn mock,
    // since spying on a module mutates it globally, not per-test. restoreMocks
    // undoes every spy/mock after each test so this can't happen again.
    restoreMocks: true,
  },
})
