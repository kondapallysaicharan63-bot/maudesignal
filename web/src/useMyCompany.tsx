// State for "Make it yours": the mode (simulated Demo MedTech Co. or the person's own company) and the person's company.
// Kept in localStorage under a versioned key when the browser allows it, in memory otherwise. Never sent anywhere.
import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import {
  addDevices as addTo,
  clearMine,
  emptyMine,
  loadMine,
  loadMode,
  removeDevice,
  saveMine,
  saveMode,
  setCompanyName as nameTo,
  setDeviceStatus,
  type Mode,
  type MineCompany,
  type NewDevice,
} from './myCompany'

export interface MineApi {
  mode: Mode
  setMode: (m: Mode) => void
  mine: MineCompany
  /** False when storage is blocked: the company is then kept in memory and the page says so. */
  persisted: boolean
  /** Product codes with stored data on this site (a code outside it is accepted with a note). */
  known: ReadonlySet<string>
  /** Product codes the sweep flags (a new device with such a code starts in Needs review). */
  flagged: ReadonlySet<string>
  apiBase: string | null
  setCompany: (name: string) => void
  add: (inputs: NewDevice[]) => void
  move: (id: string, to: string) => void
  remove: (id: string) => void
  replace: (c: MineCompany) => void
  clear: () => void
}

export const MineContext = createContext<MineApi | null>(null)
/** The Make it yours state; null outside the app (tests of the simulated views render without it). */
export const useMine = (): MineApi | null => useContext(MineContext)

export interface MineState {
  mode: Mode
  setMode: (m: Mode) => void
  mine: MineCompany
  persisted: boolean
  setCompany: (name: string) => void
  add: (inputs: NewDevice[], flagged: ReadonlySet<string>) => void
  move: (id: string, to: string) => void
  remove: (id: string) => void
  replace: (c: MineCompany) => void
  clear: () => void
}

export function useMineState(): MineState {
  const [init] = useState(() => loadMine())
  const [mine, setMine] = useState<MineCompany>(init.value)
  const [persisted, setPersisted] = useState(init.persisted)
  const [mode, setModeState] = useState<Mode>(() => loadMode())
  const ref = useRef(mine)
  const commit = useCallback((n: MineCompany) => {
    ref.current = n
    setMine(n)
    setPersisted(saveMine(n))
  }, [])
  const setMode = useCallback((m: Mode) => {
    setModeState(m)
    saveMode(m)
  }, [])
  return useMemo(
    () => ({
      mode,
      setMode,
      mine,
      persisted,
      setCompany: (name) => commit(nameTo(ref.current, name)),
      add: (inputs, flagged) => commit(addTo(ref.current, inputs, flagged)),
      move: (id, to) => commit(setDeviceStatus(ref.current, id, to)),
      remove: (id) => commit(removeDevice(ref.current, id)),
      replace: (c) => commit(c),
      clear: () => {
        ref.current = emptyMine()
        setMine(ref.current)
        setPersisted(clearMine())
      },
    }),
    [mode, setMode, mine, persisted, commit],
  )
}
