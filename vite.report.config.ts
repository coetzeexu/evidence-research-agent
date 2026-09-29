import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Library builds preserve dependency environment reads by default. The offline
  // IIFE runs in a browser with no Node `process` global, including under file://.
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
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
