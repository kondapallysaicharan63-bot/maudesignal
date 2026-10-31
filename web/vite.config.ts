import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Relative base so the static build works from any path (Vercel, GitHub Pages, file preview).
export default defineConfig({ base: './', plugins: [react()] })
