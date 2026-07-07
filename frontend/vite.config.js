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
    },
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router'],
          'vendor-element': ['element-plus', '@element-plus/icons-vue'],
          'vendor-axios': ['axios'],
          'vendor-gsap': ['gsap', 'gsap/Flip'],
        },
      },
    },
  },
})
