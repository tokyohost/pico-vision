import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 使用相对资源路径，确保 PyInstaller 解包后的 file:// 页面可以直接加载。
export default defineConfig({
  base: './',
  plugins: [vue()],
  build: {
    // macOS 12 的系统 WKWebView 是最低前端兼容基线，CSS 另做显式降级。
    target: ['es2020', 'safari15', 'chrome87', 'edge88', 'firefox78'],
    outDir: 'dist',
    emptyOutDir: true,
  },
})
