// Camera and mic screens. The live calls themselves (POST /v1/live/label, /v1/live/voice) are in live/api.ts; this file
// holds only the names and the plain-words texts the two screens share. Nothing here invents a result: without the API
// the screens show the stored runs and say so.
import { PHOTO_NOTE, VOICE_NOTE } from './live/api'
import { apiBaseFrom } from './liveCheck'

export type CaptureMode = 'label' | 'voice'

/** Shown before any photo is chosen or sent. */
export const PHOTO_WARNING = PHOTO_NOTE
/** Shown before any recording is made or sent. */
export const VOICE_WARNING = VOICE_NOTE

/** Why nothing live happened when the build has no API address. */
export const UNCONFIGURED_TEXT = 'The live service is not connected in this build, so nothing can be sent. The recorded run below shows what a reading looks like.'

export { apiBaseFrom }
