import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

const backend = 'http://127.0.0.1:9000'

const apiProxy = {
  target: backend,
  changeOrigin: true,
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': apiProxy,
      '/health': apiProxy,
      '/ping': apiProxy,
      '/posts': apiProxy,
      '/events': apiProxy,
    },
  },
})
