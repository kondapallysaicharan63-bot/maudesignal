import react from '@vitejs/plugin-react'
import { execSync } from 'node:child_process'
import { defineConfig, loadEnv } from 'vite'

// Relative base so the static build works from any path (Vercel, GitHub Pages, file preview).
export default defineConfig(({ mode }) => {
  // The build's layout default (classic | v2) is also written into index.html, so the first-paint theme script knows
  // which layout will load. Letters and digits only.
  const layout = (loadEnv(mode, process.cwd(), 'VITE_').VITE_LAYOUT_DEFAULT ?? 'classic').replace(/[^a-z0-9]/gi, '')
  // Build commit printed on every export (PRD-25): Vercel's git SHA, else the local checkout, else "unknown".
  let commit = (process.env.VERCEL_GIT_COMMIT_SHA ?? '').trim()
  if (!commit) {
    try {
      commit = execSync('git rev-parse HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()
    } catch {
      commit = 'unknown'
    }
  }
  return {
    base: './',
    define: { __MS_COMMIT__: JSON.stringify(commit.replace(/[^0-9a-f]/gi, '').slice(0, 40) || 'unknown') },
    plugins: [
      react(),
      { name: 'ms-layout-default', transformIndexHtml: (html: string) => html.replace('__MS_LAYOUT_DEFAULT__', layout) },
    ],
  }
})
