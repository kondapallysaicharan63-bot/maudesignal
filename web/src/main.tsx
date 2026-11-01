import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { inject } from '@vercel/analytics'
import App from './App'
import AppV2 from './v2/AppV2'
import { layoutMode } from './layoutFlag'
import { stripChatId, stripRef } from './analytics'
import './styles/fonts.css'
import './styles/tokens.css'
import './styles/maudesignal.css'
import './index.css'
import './buddy.css'

// Vercel Web Analytics: page views only, no custom events; the personal ref code (and a v2 chat id) is stripped.
inject({ beforeSend: (e) => ({ ...e, url: stripChatId(stripRef(e.url)) }) })

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    {layoutMode() === 'v2' ? <AppV2 /> : <App />}
  </StrictMode>,
)
