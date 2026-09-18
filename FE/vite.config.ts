import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// FE chạy ở 3070, BE (NestJS) ở 8070, AI Bridge ở 8071 — xem README.md.
// strictPort: true => nếu 3070 bận thì Vite báo lỗi ngay, KHÔNG tự nhảy sang cổng
// khác (chính việc tự nhảy cổng đã từng đè lên cổng của BE gây EADDRINUSE).
// allowedHosts: Vite 5 chặn Host lạ (chống DNS-rebinding). Truy cập qua Cloudflare
// tunnel phải khai báo domain ở đây, nếu không sẽ bị "Blocked request. This host
// ("...") is not allowed". Tiền tố "." khớp domain gốc và mọi subdomain.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3070,
    strictPort: true,
    allowedHosts: ['.jupiter-ai.pro', 'callphone.jupiter-ai.pro'],
    proxy: {
      '/api': {
        target: 'http://localhost:8070',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
