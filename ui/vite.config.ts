import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/** Where `python run.py` serves the engine from, for `npm run dev`. */
const ENGINE = 'http://127.0.0.1:8420'

// The build output is committed to git (see ui/README.md): server.py serves
// ui/dist/ directly, so `python run.py` needs no Node toolchain.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // The patch panel is meant to run offline on modest hardware; keeping
    // sourcemaps out keeps the committed bundle small.
    sourcemap: false,
  },
  server: {
    proxy: {
      '/api': { target: ENGINE, changeOrigin: true },
      // SSE: the proxy must not buffer, hence no compression on this route.
      '/events': { target: ENGINE, changeOrigin: true },
    },
  },
})
