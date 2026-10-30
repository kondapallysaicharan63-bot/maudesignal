// Draws a camera frame or a chosen file onto a canvas and encodes a fresh JPEG. A canvas JPEG carries no EXIF (no
// location, no camera serial, no time), so what leaves the page is only pixels. The server re-encodes it again.
import { fitSize } from './label'

function canvasToJpeg(c: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) =>
    c.toBlob((b) => (b ? resolve(b) : reject(new Error('encode-failed'))), 'image/jpeg', 0.9),
  )
}

/** One frame of a playing <video> as a JPEG. */
export async function frameToJpeg(video: HTMLVideoElement): Promise<Blob> {
  const { width, height } = fitSize(video.videoWidth, video.videoHeight)
  if (!width) throw new Error('no-frame')
  const c = document.createElement('canvas')
  c.width = width
  c.height = height
  c.getContext('2d')?.drawImage(video, 0, 0, width, height)
  return canvasToJpeg(c)
}

/** A chosen image file as a JPEG (orientation applied, metadata dropped). Throws when the browser cannot decode it. */
export async function fileToJpeg(file: File): Promise<Blob> {
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' })
  try {
    const { width, height } = fitSize(bmp.width, bmp.height)
    const c = document.createElement('canvas')
    c.width = width
    c.height = height
    c.getContext('2d')?.drawImage(bmp, 0, 0, width, height)
    return await canvasToJpeg(c)
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
