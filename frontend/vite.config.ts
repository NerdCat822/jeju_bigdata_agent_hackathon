/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 개발 서버(5173)는 /api 요청을 백엔드(8501)로 넘겨요. 배포본은 백엔드가 같은 주소에서 화면도 함께 내줘요.
const backend = process.env.MEOMUL_API ?? 'http://127.0.0.1:8501'

export default defineConfig({
  // 빌드한 화면이 자기 파일을 상대 경로로 찾게 해요. 그래야 같은 빌드가 http://localhost:3000/ 에서도,
  // 게이트웨이 뒤 하위 경로(예: /meomulmeong/)에서도 열려요. 개발 서버와 테스트에서는 '/' 로 동작해요.
  base: './',
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
