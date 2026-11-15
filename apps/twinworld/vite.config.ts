import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const globeTextures: Plugin = {
  name: 'globe-textures',
  apply: 'build',
  generateBundle() {
    for (const body of ['earth', 'mars', 'moon']) {
      this.emitFile({
        type: 'asset',
        fileName: `textures/${body}.jpg`,
        source: readFileSync(resolve(process.cwd(), `public/textures/${body}.jpg`)),
      });
    }
  },
};

export default defineConfig({
  build: { copyPublicDir: false },
  plugins: [react(), tailwindcss(), globeTextures],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
});
