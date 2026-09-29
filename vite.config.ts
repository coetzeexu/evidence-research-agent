import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: {
    outDir: 'dist/web',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('echarts')) return 'charts';
            if (id.includes('zrender')) return 'chart-renderer';
            if (
              id.includes('react-markdown') ||
              id.includes('micromark') ||
              id.includes('mdast') ||
              id.includes('remark') ||
              id.includes('unified')
            )
              return 'markdown';
            return 'vendor';
          }
        },
      },
    },
  },
});
