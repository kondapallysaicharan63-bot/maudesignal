// Draws a camera frame or a chosen file onto a canvas and encodes a fresh JPEG (longest side 1600 px, quality 0.85, then
// 0.7 and 0.55 if the result is over 4 MB). A canvas JPEG carries no EXIF (no location, no camera serial, no time), so
// what leaves the page is only pixels; the original file bytes are never sent. The server re-encodes it again.
import { MAX_IMAGE_BYTES } from './api'
import { fitSize } from './label'

/** JPEG qualities tried in order: the first that fits under the size limit is sent. */
export const PHOTO_QUALITIES: readonly number[] = [0.85, 0.7, 0.55]

/** Thrown when a photo cannot be sent: still too big at the lowest quality, or no pixels to draw. */
export class PhotoError extends Error {
  constructor(public kind: 'too_big' | 'no_frame' | 'encode_failed') {
    super(kind)
    this.name = 'PhotoError'
  }
}

export const PHOTO_TOO_BIG_TEXT = `This photo is still larger than ${MAX_IMAGE_BYTES / (1024 * 1024)} MB after it was shrunk. Take it again closer to the label, or choose a smaller photo.`

/** Shown when the browser's encoder returns no picture. */
export const PHOTO_ENCODE_FAILED_TEXT = 'This browser could not make a picture to send. Try again, or choose a different photo.'

/** The minimal canvas surface this file needs (a real HTMLCanvasElement fits; tests pass a fake). */
export interface PhotoCanvas {
  width: number
  height: number
  getContext(kind: '2d'): { drawImage(src: never, x: number, y: number, w: number, h: number): void } | null
  toBlob(cb: (b: Blob | null) => void, type: string, quality: number): void
}

/**
 * Encodes with each quality in turn and returns the first result of at most `maxBytes`. Throws PhotoError('too_big') when
 * even the last quality is over the limit, and PhotoError('encode_failed') when the encoder returns an empty result. The original file or frame is never an option here: only encoder output is returned.
 */
export async function encodeWithin(
  encode: (quality: number) => Promise<Blob>,
  maxBytes: number = MAX_IMAGE_BYTES,
  qualities: readonly number[] = PHOTO_QUALITIES,
): Promise<Blob> {
  for (const q of qualities) {
    const b = await encode(q)
    if (b.size === 0) throw new PhotoError('encode_failed') // the encoder returned nothing: not "too big"
    if (b.size <= maxBytes) return b
  }
  throw new PhotoError('too_big')
}

/**
 * Draws a source of srcW x srcH (longest side cut to PHOTO_MAX_SIDE) onto a fresh canvas and encodes a JPEG that fits the
 * size limit. A canvas JPEG carries no EXIF, so the result is only pixels.
 */
export async function drawToJpeg(
  source: unknown,
  srcW: number,
  srcH: number,
  makeCanvas: () => PhotoCanvas = () => document.createElement('canvas') as unknown as PhotoCanvas,
  maxBytes: number = MAX_IMAGE_BYTES,
): Promise<Blob> {
  const { width, height } = fitSize(srcW, srcH)
  if (!width) throw new PhotoError('no_frame')
  const c = makeCanvas()
  c.width = width
  c.height = height
  c.getContext('2d')?.drawImage(source as never, 0, 0, width, height)
  return encodeWithin(
    (q) => new Promise<Blob>((resolve, reject) => c.toBlob((b) => (b ? resolve(b) : reject(new PhotoError('encode_failed'))), 'image/jpeg', q)),
    maxBytes,
  )
}

/** One frame of a playing <video> as a JPEG (longest side 1600 px, quality 0.85, lower if needed). */
export const frameToJpeg = (video: HTMLVideoElement): Promise<Blob> => drawToJpeg(video, video.videoWidth, video.videoHeight)

/** A chosen image file as a JPEG (orientation applied, metadata dropped). Throws when the browser cannot decode it. */
export async function fileToJpeg(file: File): Promise<Blob> {
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' })
  try {
    return await drawToJpeg(bmp, bmp.width, bmp.height)
  } finally {
    bmp.close()
  }
}

/** Why the camera could not be used, in plain words. */
export function cameraErrorText(e: unknown): string {
  const name = (e as { name?: string } | null)?.name ?? ''
  if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError')
    return 'Camera permission was denied. Allow the camera in the browser, or upload a photo instead. The recorded label runs are shown below.'
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError')
    return 'No camera was found. Upload a photo instead. The recorded label runs are shown below.'
  if (name === 'NotReadableError') return 'The camera is in use by another program. Upload a photo instead. The recorded label runs are shown below.'
  return 'The camera could not be used. Upload a photo instead. The recorded label runs are shown below.'
}
