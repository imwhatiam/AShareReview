import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

import { createDevelopmentApiProxy } from './src/api/developmentProxy'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '')

  return {
    envDir: '..',
    plugins: [react()],
    server: {
      proxy: createDevelopmentApiProxy(env.VITE_DEV_BACKEND_ORIGIN),
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.js',
    },
  }
})
