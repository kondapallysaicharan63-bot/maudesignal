import { useEffect, useRef, useState } from 'react'

/** Renders every page of a stored PDF onto canvases (pdf.js, bundled: no network, works on phones). */
export function PdfView({ url, title }: { url: string; title: string }) {
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
      const doc = await pdfjs.getDocument(url).promise
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
      {state.kind === 'loading' && <p className="m-0 text-ink-3">Loading the PDF…</p>}
      {state.kind === 'error' && (
        <p className="ms-banner ms-banner--err m-0">The PDF could not be shown here ({state.msg}). Use the links below.</p>
      )}
      <div ref={host} className="max-h-[56dvh] overflow-y-auto rounded-md border border-rule bg-sunk p-2" />
      {state.kind === 'ok' && <p className="m-0 mt-1 text-[14px] text-ink-3">{state.pages} pages</p>}
    </div>
  )
}
