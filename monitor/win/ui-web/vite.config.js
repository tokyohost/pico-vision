import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 使用相对资源路径，确保 PyInstaller 解包后的 file:// 页面可以直接加载。
export default defineConfig({
  base: './',
  plugins: [vue()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
