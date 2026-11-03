// Build version + commit printed on every export and on the Validation page (PRD-25), so a trial team can say which
// build it used. The version is package.json's; the commit is injected at build time (vite.config.ts).
import pkg from '../../package.json'

export const BUILD_VERSION: string = (pkg as { version: string }).version
export const BUILD_COMMIT: string = typeof __MS_COMMIT__ === 'string' ? __MS_COMMIT__ : 'unknown'
export const BUILD_COMMIT_SHORT = BUILD_COMMIT === 'unknown' ? 'unknown' : BUILD_COMMIT.slice(0, 12)

/** "0.1.0 · commit 1a2b3c4d5e6f". */
export const buildLine = (): string => `${BUILD_VERSION} · commit ${BUILD_COMMIT_SHORT}`
