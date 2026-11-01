import { useEffect, useRef, useState } from 'react'

/** Renders every page of a stored PDF onto canvases (pdf.js, bundled: no network, works on phones). */
export function PdfView({ url, title, v2 = false }: { url: string; title: string; v2?: boolean }) {
  const host = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<{ kind: 'loading' } | { kind: 'rendering'; pages: number } | { kind: 'ok'; pages: number } | { kind: 'error'; msg: string }>({
    kind: 'loading',
  })

  useEffect(() => {
    let cancelled = false
    const el = host.current
    if (!el) return
    el.replaceChildren()
    setState({ kind: 'loading' })
    ;(async () => {
      const pdfjs = await import('pdfjs-dist')
      const worker = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
      pdfjs.GlobalWorkerOptions.workerSrc = worker
      // An absolute address: pdf.js resolves a relative one against the page address, not <base> (v2 pages live at
      // /evidence/review and similar, where "./data/..." would fetch the app page instead of the PDF).
      const doc = await pdfjs.getDocument(new URL(url, document.baseURI).href).promise
      const cssWidth = Math.max(280, el.clientWidth)
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      for (let n = 1; n <= doc.numPages; n++) {
        const page = await doc.getPage(n)
        if (cancelled) return
        const base = page.getViewport({ scale: 1 })
        const scale = cssWidth / base.width
        const vp = page.getViewport({ scale: scale * dpr })
        const canvas = document.createElement('canvas')
        canvas.width = Math.floor(vp.width)
        canvas.height = Math.floor(vp.height)
        canvas.style.width = '100%'
        canvas.style.display = 'block'
        canvas.style.marginBottom = '8px'
        canvas.setAttribute('role', 'img')
        canvas.setAttribute('aria-label', `${title}, page ${n} of ${doc.numPages}`)
        const ctx = canvas.getContext('2d')
        if (!ctx) throw new Error('canvas is not available')
        await page.render({ canvasContext: ctx, viewport: vp }).promise
        if (cancelled) return
        el.appendChild(canvas)
        if (n === 1) setState({ kind: 'rendering', pages: doc.numPages })
      }
      if (!cancelled) setState({ kind: 'ok', pages: doc.numPages })
    })().catch((e: unknown) => {
      if (!cancelled) setState({ kind: 'error', msg: e instanceof Error ? e.message : String(e) })
    })
    return () => {
      cancelled = true
    }
  }, [url, title])

  return (
    <div>
      {state.kind === 'loading' && <p className="m-0 text-ink-2">Loading the PDF…</p>}
      {state.kind === 'error' &&
        (v2 ? (
          <p className="ms2-muted m-0" role="status" data-testid="pdf-unavailable">
            Preview unavailable. Open in a new tab or download below.
          </p>
        ) : (
          <p className="ms-banner ms-banner--err m-0">The PDF could not be shown here ({state.msg}). Use the links below.</p>
        ))}
      <div
        ref={host}
        className="max-h-[56dvh] overflow-y-auto rounded-md border border-rule bg-sunk p-2"
        hidden={v2 && state.kind === 'error' ? true : undefined}
      />
      {state.kind === 'ok' && <p className="m-0 mt-1 text-[15px] text-ink-2">{state.pages} pages</p>}
    </div>
  )
}
