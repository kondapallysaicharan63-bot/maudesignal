import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { inject } from '@vercel/analytics'
import App from './App'
import { stripRef } from './analytics'
import './styles/fonts.css'
import './styles/tokens.css'
import './styles/maudesignal.css'
import './index.css'

// Vercel Web Analytics: page views only, no custom events; the personal ref code is stripped.
inject({ beforeSend: (e) => ({ ...e, url: stripRef(e.url) }) })

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
