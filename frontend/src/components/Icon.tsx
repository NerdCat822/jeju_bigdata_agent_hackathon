import type { ReactNode } from 'react'

const PATHS = {
  check: 'M4.5 10.5l3.5 3.5 7.5-8',
  x: 'M5 5l10 10M15 5L5 15',
  alert: 'M10 3.5l7.5 13h-15l7.5-13zM10 8.5v4M10 14.8v.2',
  chevron: 'M7 4.5l5.5 5.5L7 15.5',
  arrow: 'M4 10h12M11 5l5 5-5 5',
  pin: 'M10 17.5s5.5-5.2 5.5-9.3a5.5 5.5 0 10-11 0c0 4.1 5.5 9.3 5.5 9.3zM10 10a2 2 0 100-4 2 2 0 000 4z',
  copy: 'M7.5 7.5h8v9h-8zM4.5 12.5v-9h8',
  external: 'M8 4.5H4.5v11h11V12M11 4.5h4.5V9M15.5 4.5L9 11',
  download: 'M10 3.5v9M6 9l4 4 4-4M4 16.5h12',
  edit: 'M4.5 15.5l1-4 8-8 3 3-8 8-4 1zM11.5 5.5l3 3',
  play: 'M6.5 4.5l9 5.5-9 5.5z',
  info: 'M10 17a7 7 0 100-14 7 7 0 000 14zM10 9v4.5M10 6.5v.2',
  doc: 'M5.5 3.5h6l3 3v10h-9zM11.5 3.5v3h3M7.5 10.5h5M7.5 13.5h5',
  home: 'M3.5 9.5L10 4l6.5 5.5M5.5 8.5v7.5h9V8.5',
} as const

export type IconName = keyof typeof PATHS

/** 작은 선 아이콘. 글자 옆 장식이라 화면 낭독기에는 숨겨요. */
export function Icon({ name, size = 16 }: { name: IconName; size?: number }): ReactNode {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name]} fill={name === 'play' ? 'currentColor' : 'none'} />
    </svg>
  )
}

export function Spinner({ size = 14 }: { size?: number }): ReactNode {
  return <span className="spinner" style={{ width: size, height: size }} aria-hidden="true" />
}
