// A tiny text-only PDF writer (Helvetica / Courier, US Letter, wrapped lines, "Page X of Y" footer). Same design as
// src/maudesignal/pms/simple_pdf.py; nothing is embedded and no library is loaded. Characters outside Latin-1 are
// written as "?".

const PAGE_W = 612
const PAGE_H = 792
const MARGIN = 54
const LEADING = 13

export type Para = [style: 'h1' | 'h2' | 'body' | 'mono', text: string]

const latin1 = (s: string): string =>
  s
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201c\u201d]/g, '"')
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/\u2026/g, '...')
    .replace(/\u00b7/g, '\u00b7')
    .replace(/[^\x00-\xff]/g, '?')
const esc = (s: string): string => latin1(s).replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)')

function wrap(text: string, width: number): string[] {
  const out: string[] = []
  for (const raw of text.split('\n')) {
    const words = raw.split(/\s+/).filter(Boolean)
    if (!words.length) {
      out.push('')
      continue
    }
    let line = ''
    for (let w of words) {
      while (w.length > width) {
        if (line) {
          out.push(line)
          line = ''
        }
        out.push(w.slice(0, width))
        w = w.slice(width)
      }
      if (!line) line = w
      else if (line.length + 1 + w.length <= width) line += ` ${w}`
      else {
        out.push(line)
        line = w
      }
    }
    if (line) out.push(line)
  }
  return out
}

export function renderPdf(title: string, paras: Para[], footer: string): Uint8Array {
  const sizes = { h1: 16, h2: 12, body: 10, mono: 9 }
  const fonts = { h1: 'F2', h2: 'F2', body: 'F1', mono: 'F3' }
  const lines: Para[] = []
  for (const [style, text] of paras) {
    const width = style === 'h1' ? 70 : style === 'h2' ? 85 : 95
    for (const l of text ? wrap(text, width) : ['']) lines.push([style, l])
  }
  const perPage = Math.floor((PAGE_H - 2 * MARGIN - 20) / LEADING)
  const pages: Para[][] = []
  for (let i = 0; i < lines.length; i += perPage) pages.push(lines.slice(i, i + perPage))
  if (!pages.length) pages.push([])
  const objs: string[] = []
  const add = (s: string) => objs.push(s)
  add('<< /Type /Catalog /Pages 2 0 R >>')
  add('PAGES')
  add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
  add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>')
  add('<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>')
  const kids: number[] = []
  pages.forEach((page, idx) => {
    let y = PAGE_H - MARGIN
    const ops = ['BT']
    for (const [style, text] of page) {
      ops.push(`/${fonts[style]} ${sizes[style]} Tf 1 0 0 1 ${MARGIN} ${y} Tm (${esc(text)}) Tj`)
      y -= LEADING + (style === 'h1' ? 4 : 0)
    }
    ops.push(`/F1 8 Tf 1 0 0 1 ${MARGIN} ${MARGIN - 20} Tm (${esc(`${footer} | Page ${idx + 1} of ${pages.length}`)}) Tj`)
    ops.push('ET')
    const stream = ops.join('\n')
    add(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`)
    const content = objs.length
    add(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE_W} ${PAGE_H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> /Contents ${content} 0 R >>`,
    )
    kids.push(objs.length)
  })
  objs[1] = `<< /Type /Pages /Kids [${kids.map((k) => `${k} 0 R`).join(' ')}] /Count ${kids.length} >>`
  add(`<< /Title (${esc(title)}) /Producer (MaudeSignal pdf.ts) >>`)
  const info = objs.length
  let out = '%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'
  const offsets: number[] = []
  objs.forEach((body, i) => {
    offsets.push(out.length)
    out += `${i + 1} 0 obj\n${body}\nendobj\n`
  })
  const xref = out.length
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`
  for (const o of offsets) out += `${String(o).padStart(10, '0')} 00000 n \n`
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R /Info ${info} 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  // Every character is Latin-1 here, so one byte per character keeps the offsets right.
  const bytes = new Uint8Array(out.length)
  for (let i = 0; i < out.length; i++) bytes[i] = out.charCodeAt(i) & 0xff
  return bytes
}

/** All text shown with Tj (tests). */
export function pdfText(bytes: Uint8Array): string {
  let s = ''
  for (const b of bytes) s += String.fromCharCode(b)
  return Array.from(s.matchAll(/\((.*?)(?<!\\)\) Tj/gs), (m) => m[1].replace(/\\\(/g, '(').replace(/\\\)/g, ')').replace(/\\\\/g, '\\')).join('\n')
}

/** Markdown (as produced by noteMarkdown) to PDF paragraphs. */
export function markdownParas(md: string): Para[] {
  return md.split('\n').map((l): Para => (l.startsWith('# ') ? ['h1', l.slice(2)] : l.startsWith('## ') ? ['h2', l.slice(3)] : ['body', l.replace(/\*\*/g, '')]))
}

/** Save a file in the browser. */
export function download(name: string, data: string | Uint8Array, type: string): void {
  const blob = new Blob([typeof data === 'string' ? data : (data as BlobPart)], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
