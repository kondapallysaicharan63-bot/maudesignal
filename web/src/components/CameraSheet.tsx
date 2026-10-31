// "Take photo" on a computer: the live camera opens at once (back camera preferred), with Shutter, then Retake or Use
// photo. If the camera cannot be used (permission refused, no camera, a page that is not secure) the dialog closes and the
// caller falls back to the file picker with a short reason. The picture is a fresh JPEG drawn from the video (no EXIF).
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '../icons'
import { frameToJpeg, PHOTO_ENCODE_FAILED_TEXT, PHOTO_TOO_BIG_TEXT, PhotoError } from '../live/photo'

/** The short reason shown when the camera falls back to the file picker. */
export function cameraFallbackText(e: unknown): string {
  const name = (e as { name?: string } | null)?.name ?? ''
  if (name === 'insecure') return 'Camera needs a secure (https) page — choose a photo instead'
  if (name === 'unsupported') return 'This browser has no camera access — choose a photo instead'
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError' || name === 'OverconstrainedError') return 'No camera found — choose a photo instead'
  if (name === 'NotReadableError') return 'Camera in use by another program — choose a photo instead'
  return 'Camera blocked — choose a photo instead'
}

const named = (name: string): Error => Object.assign(new Error(name), { name })

/** Asks for the camera: back camera preferred, any camera if that is refused as impossible. */
export async function openCamera(md: MediaDevices | undefined = typeof navigator === 'undefined' ? undefined : navigator.mediaDevices, secure: boolean = typeof window === 'undefined' || window.isSecureContext !== false): Promise<MediaStream> {
  if (!secure) throw named('insecure')
  if (!md?.getUserMedia) throw named('unsupported')
  try {
    return await md.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
  } catch (e) {
    const name = (e as { name?: string })?.name
    if (name === 'OverconstrainedError') return md.getUserMedia({ video: true, audio: false })
    throw e
  }
}

export function CameraSheet({ onUse, onClose, onFail }: {
  /** The picture the person chose to attach. */
  onUse: (jpeg: Blob) => void
  onClose: () => void
  /** The camera could not be used: a short reason for the file-picker fallback. */
  onFail: (reason: string) => void
}) {
  const video = useRef<HTMLVideoElement>(null)
  const stream = useRef<MediaStream | null>(null)
  const dialog = useRef<HTMLDivElement>(null)
  const shutter = useRef<HTMLButtonElement>(null)
  const [ready, setReady] = useState(false)
  const [shot, setShot] = useState<{ blob: Blob; url: string } | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  const stopCamera = useCallback(() => {
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
  }, [])

  useEffect(() => {
    let alive = true
    openCamera()
      .then((s) => {
        if (!alive) {
          s.getTracks().forEach((t) => t.stop())
          return
        }
        stream.current = s
        if (video.current) {
          video.current.srcObject = s
          void video.current.play().catch(() => undefined)
        }
        setReady(true)
      })
      .catch((e: unknown) => {
        if (alive) onFail(cameraFallbackText(e))
      })
    return () => {
      alive = false
      stopCamera()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => () => {
    if (shot) URL.revokeObjectURL(shot.url)
  }, [shot])

  useEffect(() => {
    if (ready && !shot) shutter.current?.focus()
  }, [ready, shot])

  const take = async () => {
    if (!video.current) return
    setProblem(null)
    try {
      const blob = await frameToJpeg(video.current)
      setShot({ blob, url: URL.createObjectURL(blob) })
    } catch (e) {
      if (e instanceof PhotoError && e.kind === 'too_big') setProblem(PHOTO_TOO_BIG_TEXT)
      else if (e instanceof PhotoError && e.kind === 'encode_failed') setProblem(PHOTO_ENCODE_FAILED_TEXT)
      else setProblem('No picture could be taken yet. Wait a second for the camera to start, then try again.')
    }
  }

  // A modal dialog: Escape closes, Tab stays inside.
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation()
      onClose()
    } else if (e.key === 'Tab' && dialog.current) {
      const f = Array.from(dialog.current.querySelectorAll<HTMLElement>('button:not([disabled])'))
      if (f.length === 0) return
      const first = f[0]
      const last = f[f.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  const btn = 'ms-btn !min-h-11 flex-1 sm:flex-none'
  // A portal to <body>, so the scrim covers the whole page (sidebar included), above every pane.
  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-end justify-center p-3 sm:items-center" data-testid="camera-sheet">
      <div className="ws-scrim" aria-hidden="true" onClick={onClose} />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="camera-sheet-title"
        onKeyDown={onKey}
        className="relative w-full max-w-xl rounded-md border border-rule-strong bg-surface p-3 shadow-[var(--shadow-pop)]"
      >
        <div className="mb-2 flex items-center justify-between gap-2">
          <h2 id="camera-sheet-title" className="m-0 text-[17px] font-semibold text-ink">
            Take a photo of the device label
          </h2>
          <button type="button" className="ws-icon-btn min-h-11 min-w-11" onClick={onClose} aria-label="Close the camera" data-testid="camera-close">
            <Icon name="close" />
          </button>
        </div>
        <div className="relative overflow-hidden rounded-md border border-rule bg-sunk">
          <video
            ref={video}
            playsInline
            muted
            autoPlay
            aria-label="Camera preview"
            data-testid="camera-live"
            className={['block max-h-[55dvh] w-full object-contain', shot ? 'hidden' : ''].join(' ')}
          />
          {shot && <img src={shot.url} alt="The photo you took" className="block max-h-[55dvh] w-full object-contain" data-testid="camera-shot" />}
          {!ready && !shot && (
            <p role="status" className="absolute inset-0 m-0 flex items-center justify-center text-[16px] text-ink-2">
              Starting the camera…
            </p>
          )}
        </div>
        <p className="m-0 mt-2 text-[15px] text-ink-2">Photo is read once and not stored. Do not photograph patient details.</p>
        {problem && (
          <p role="alert" className="ms-banner ms-banner--err mt-2">
            <span className="ws-wrap">{problem}</span>
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {shot ? (
            <>
              <button
                type="button"
                className={`${btn} ms-btn--secondary`}
                onClick={() => {
                  setShot(null)
                }}
                data-testid="camera-retake"
              >
                Retake
              </button>
              <button
                type="button"
                className={`${btn} ws-btn-primary`}
                onClick={() => {
                  stopCamera()
                  onUse(shot.blob)
                }}
                data-testid="camera-use"
                autoFocus
              >
                <Icon name="check" size={18} /> Use photo
              </button>
            </>
          ) : (
            <button
              ref={shutter}
              type="button"
              className={`${btn} ws-btn-primary`}
              onClick={() => void take()}
              disabled={!ready}
              data-testid="camera-shutter"
            >
              <Icon name="camera" size={18} /> Take picture
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
