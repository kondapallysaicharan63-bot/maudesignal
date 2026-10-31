import { useEffect, useState } from 'react'
import { ASK_FOR_KEY, connectSteps, fetchConnect, FALLBACK_INFO, type ConnectInfo } from '../connect'
import { Icon } from '../icons'

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>

function CopyButton({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setState('copied')
    } catch {
      setState('failed')
    }
    setTimeout(() => setState('idle'), 2500)
  }
  return (
    <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 44 }} onClick={() => void copy()} aria-label={`Copy ${label}`} data-testid={`copy-${label.replace(/\s+/g, '-').toLowerCase()}`}>
      {state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed: select the text' : 'Copy'}
    </button>
  )
}

function Row({ label, value, copyLabel }: { label: string; value: string; copyLabel: string }) {
  return (
    <div className="flex flex-col gap-1 border-t border-rule py-3 first:border-t-0 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
      <div className="min-w-0">
        <p className="m-0 text-[15px] text-ink-2">{label}</p>
        <p className="ms-code ws-wrap m-0 !text-[16px] !text-ink" data-testid={`value-${copyLabel.replace(/\s+/g, '-').toLowerCase()}`}>
          {value}
        </p>
      </div>
      <CopyButton text={value} label={copyLabel} />
    </div>
  )
}

/** The "Connect to Muse" page: addresses, the demo key when the API gives one, three steps, privacy and terms. */
export function ConnectView({ apiBase, fetcher }: { apiBase: string | null; fetcher?: Fetcher }) {
  const [info, setInfo] = useState<ConnectInfo | null>(apiBase ? null : FALLBACK_INFO)
  useEffect(() => {
    let live = true
    if (!apiBase) {
      setInfo(FALLBACK_INFO)
      return
    }
    void fetchConnect(apiBase, fetcher).then((i) => live && setInfo(i))
    return () => {
      live = false
    }
  }, [apiBase, fetcher])
  const i = info ?? FALLBACK_INFO
  return (
    <div className="space-y-4" data-testid="connect-view">
      <div>
        <p className="ms-kicker m-0">For reviewers</p>
        <h1 className="t-headline m-0 mt-1" style={{ fontSize: 'clamp(24px, 4vw, 32px)' }}>
          Connect to Muse
        </h1>
        <p className="mt-2 max-w-2xl text-ink-2">
          Add MaudeSignal to Muse as a custom connector. It answers from stored public FDA records, read-only. Signals for a person to review; nothing is filed with FDA.
        </p>
      </div>

      {!info && <p className="m-0 text-ink-2" role="status">Loading the connector details…</p>}
      {info && !i.fromApi && (
        <p className="ms-banner ms-banner--warn m-0" data-testid="connect-fallback">
          <span className="ws-wrap">The connector service did not answer, so these are the fixed addresses. {ASK_FOR_KEY}</span>
        </p>
      )}

      <article className="rounded-md border border-rule bg-surface p-4" aria-label="Addresses and key">
        <h2 className="t-title m-0">Addresses</h2>
        <Row label="MCP address" value={i.mcp_url} copyLabel="MCP address" />
        <Row label="OpenAPI file" value={i.openapi_url} copyLabel="OpenAPI address" />
        <div className="border-t border-rule pt-3" data-testid="demo-key-block">
          <h2 className="t-title m-0">Demo key</h2>
          {i.demo_key ? (
            <>
              <Row label={`Paste it into the ${i.key_header} header`} value={i.demo_key} copyLabel="demo key" />
              <p className="m-0 text-[16px] text-ink-2" data-testid="demo-key-limits">
                {i.limits.note}
              </p>
            </>
          ) : (
            <p className="m-0 mt-1 text-[17px]" data-testid="no-demo-key">
              {ASK_FOR_KEY} <span className="text-ink-2">{i.limits.note}</span>
            </p>
          )}
        </div>
      </article>

      <article className="rounded-md border border-rule bg-surface p-4" aria-label="Three steps">
        <h2 className="t-title m-0">Three steps</h2>
        <ol className="m-0 mt-2 list-none space-y-3 p-0" data-testid="connect-steps">
          {connectSteps(i).map((s) => (
            <li key={s.n} className="flex gap-3">
              <span className="ms-num flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-inverse text-[17px] font-bold text-on-inverse" aria-hidden="true">
                {s.n}
              </span>
              <span className="ws-wrap min-w-0 pt-0.5 text-[17px]">
                <span className="sr-only">Step {s.n}: </span>
                {s.text}
              </span>
            </li>
          ))}
        </ol>
      </article>

      <p className="m-0 flex flex-wrap items-center gap-x-5 text-[17px]">
        <a className="inline-flex min-h-11 items-center gap-1 text-accent underline" href={i.privacy_url} target="_blank" rel="noreferrer noopener" data-testid="link-privacy">
          Privacy <Icon name="chevron" size={16} />
        </a>
        <a className="inline-flex min-h-11 items-center gap-1 text-accent underline" href={i.terms_url} target="_blank" rel="noreferrer noopener" data-testid="link-terms">
          Terms <Icon name="chevron" size={16} />
        </a>
        <a className="inline-flex min-h-11 items-center gap-1 text-accent underline" href={i.openapi_url} target="_blank" rel="noreferrer noopener">
          OpenAPI file <Icon name="chevron" size={16} />
        </a>
      </p>
    </div>
  )
}
