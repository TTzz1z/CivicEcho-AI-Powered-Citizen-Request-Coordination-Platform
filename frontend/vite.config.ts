import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig(() => ({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8001', changeOrigin: true },
      '/rasa': { target: 'http://localhost:5005', changeOrigin: true, rewrite: p => p.replace(/^\/rasa/, '') },
    },
  },
  build:{
    chunkSizeWarningLimit:650,
    rollupOptions:{output:{manualChunks(id){
      if(!id.includes('node_modules'))return
      if(id.includes('/echarts/')||id.includes('/zrender/'))return 'charts-vendor'
      if(id.includes('/@tanstack/'))return 'query-vendor'
      if(id.includes('/react/')||id.includes('/react-dom/')||id.includes('/react-router'))return 'react-vendor'
      if(id.includes('/rc-table/')||id.includes('/rc-virtual-list/'))return 'antd-table-runtime'
      if(id.includes('/rc-field-form/'))return 'antd-form-runtime'
      if(id.includes('/rc-picker/'))return 'antd-date-runtime'
      if(id.includes('/@ant-design/icons/'))return 'antd-icons'
    }}}},
  test: { environment: 'jsdom', setupFiles: './src/test/setup.ts', css: true, exclude: ['e2e/**', 'node_modules/**', 'dist/**'] },
}))
