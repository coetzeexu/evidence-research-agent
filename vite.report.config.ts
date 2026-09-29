import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: 'dist/report',
    emptyOutDir: true,
    cssCodeSplit: false,
    lib: {
      entry: 'apps/web/report.tsx',
      name: 'ResearchReport',
      formats: ['iife'],
      fileName: () => 'report.js',
    },
    rollupOptions: { output: { inlineDynamicImports: true, assetFileNames: 'report.[ext]' } },
  },
});
