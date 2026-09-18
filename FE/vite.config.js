import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
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
                rewrite: function (path) { return path.replace(/^\/api/, ''); }
            }
        }
    }
});
