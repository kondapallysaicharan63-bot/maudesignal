import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// Relative base so the static build works from any path (Vercel, GitHub Pages, file preview).
export default defineConfig(({ mode }) => {
  // The build's layout default (classic | v2) is also written into index.html, so the first-paint theme script knows
  // which layout will load. Letters and digits only.
  const layout = (loadEnv(mode, process.cwd(), 'VITE_').VITE_LAYOUT_DEFAULT ?? 'classic').replace(/[^a-z0-9]/gi, '')
  return {
    base: './',
    plugins: [
      react(),
      { name: 'ms-layout-default', transformIndexHtml: (html: string) => html.replace('__MS_LAYOUT_DEFAULT__', layout) },
    ],
  }
})
