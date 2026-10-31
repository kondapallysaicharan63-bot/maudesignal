import { createContext, useContext } from 'react'
import type { MentionsResult } from './mentions'

/**
 * What screens deep in the tree need from the app shell: opening the detail panel of an alert by its id
 * (e.g. "sweep:IYN"; the element that had focus gets it back on close), and the outside-mentions inputs (API address and
 * the stored search for a code) for the "Search outside sources" box on device pages.
 */
export interface AlertPanelApi {
  openAlert: (id: string, code?: string) => void
  apiBase: string | null
  mentionsFor: (code: string) => MentionsResult | null
}

export const AlertPanelContext = createContext<AlertPanelApi>({ openAlert: () => undefined, apiBase: null, mentionsFor: () => null })

export const useAlertPanel = (): AlertPanelApi => useContext(AlertPanelContext)
