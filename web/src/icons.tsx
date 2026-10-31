// Small inline SVG icons (stroke = currentColor) so the shell needs no icon font or network.
const PATHS = {
  menu: 'M4 7h16M4 12h16M4 17h16',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zm9 16-4-4',
  plus: 'M12 5v14M5 12h14',
  check: 'm5 12.5 4.5 4.5L19 7.5',
  close: 'M6 6l12 12M18 6 6 18',
  panel: 'M4 5h16v14H4zM15 5v14',
  sidebar: 'M4 5h16v14H4zM9 5v14',
  sidebarOpen: 'M4 5h16v14H4zM9 5v14M16 9.5 13.5 12l2.5 2.5',
  sidebarShut: 'M4 5h16v14H4zM9 5v14M13 9.5l2.5 2.5-2.5 2.5',
  camera: 'M4 8h4l1.5-2h5L16 8h4v11H4zM12 10a3.2 3.2 0 1 0 0 6.4 3.2 3.2 0 0 0 0-6.4z',
  back: 'M15 6l-6 6 6 6',
  sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon: 'M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z',
  auto: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 3v18',
  chat: 'M5 5h14v10H9l-4 4z',
  mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM6 11a6 6 0 0 0 12 0M12 17v4',
  chevron: 'm9 6 6 6-6 6',
  down: 'm6 9 6 6 6-6',
  up: 'm6 15 6-6 6 6',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v5M12 8v.01',
  upload: 'M12 16V4M7 9l5-5 5 5M5 20h14',
  bell: 'M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0',
  expand: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
  warn: 'M12 3.5 2.5 20h19zM12 10v5M12 17.4v.01',
  plug: 'M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  collapse: 'M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5',
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
