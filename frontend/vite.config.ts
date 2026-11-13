/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 개발 서버(5173)는 /api 요청을 백엔드(8501)로 넘겨요. 배포본은 백엔드가 같은 주소에서 화면도 함께 내줘요.
const backend = process.env.MEOMUL_API ?? 'http://127.0.0.1:8501'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': backend } },
  preview: { proxy: { '/api': backend } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
})
