import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig(() => ({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.CIVICECHO_API_PROXY || 'http://localhost:8001', changeOrigin: true },
    },
  },
  build:{
    chunkSizeWarningLimit:650,
    rollupOptions:{output:{manualChunks(id){
      if(!id.includes('node_modules'))return
      if(id.includes('/pdfjs-dist/'))return 'pdf-vendor'
      if(id.includes('/echarts/')||id.includes('/zrender/'))return 'charts-vendor'
      if(id.includes('/@tanstack/'))return 'query-vendor'
      if(id.includes('/react/')||id.includes('/react-dom/')||id.includes('/react-router'))return 'react-vendor'
      if(id.includes('/axios/'))return 'http-vendor'
      if(
        id.includes('/@ant-design/cssinjs/')||
        id.includes('/@ant-design/cssinjs-utils/')||
        id.includes('/@ant-design/colors/')||
        id.includes('/@ant-design/fast-color/')||
        id.includes('/@rc-component/util/')||
        id.includes('/@rc-component/motion/')||
        id.includes('/@rc-component/portal/')||
        id.includes('/@rc-component/resize-observer/')||
        id.includes('/@rc-component/context/')||
        id.includes('/@emotion/')||
        id.includes('/stylis/')||
        id.includes('/react-is/')||
        id.includes('/is-mobile/')||
        id.includes('/clsx/')||
        id.includes('/@babel/runtime/')
      )return 'antd-shared'
      if(id.includes('/@ant-design/icons/')||id.includes('/@ant-design/icons-svg/'))return 'antd-icons'
      if(id.includes('/@rc-component/table/')||id.includes('/@rc-component/virtual-list/'))return 'antd-table-runtime'
      if(id.includes('/@rc-component/form/')||id.includes('/@rc-component/async-validator/'))return 'antd-form-runtime'
      if(id.includes('/@rc-component/picker/'))return 'antd-date-runtime'
    }}}},
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    // Ant Design + jsdom mounts can exceed the 5s default on cold CI runners.
    testTimeout: 20_000,
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
}))
