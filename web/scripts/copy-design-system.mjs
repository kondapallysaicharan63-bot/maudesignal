// Prebuild: copy the repo design system into src/styles/ (design-system/ is never edited here).
// If design-system/ is not reachable (web/ deployed on its own), keep the committed copies.
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '../../design-system')
const dest = resolve(here, '../src/styles')
mkdirSync(dest, { recursive: true })
for (const name of ['tokens.css', 'maudesignal.css']) {
  const from = resolve(src, name)
  const to = resolve(dest, name)
  if (existsSync(from)) {
    copyFileSync(from, to)
    console.log(`design-system: copied ${name}`)
  } else if (existsSync(to)) {
    console.warn(`design-system: ${from} not found, keeping the committed ${name}`)
  } else {
    console.error(`design-system: ${name} missing in both places`)
    process.exit(1)
  }
}
