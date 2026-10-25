import {fileURLToPath} from 'node:url';
import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {BUILDER_BASE} from './src/paths.js';

export default defineConfig({
  base: BUILDER_BASE,
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL('../../mockups/mvp4/pc-builder/', import.meta.url)),
    emptyOutDir: true,
  },
  server: {host: '127.0.0.1'},
});
