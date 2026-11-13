import { ArrowRight, Check, ChevronRight, Copy, Download, ExternalLink, FileText, House, Info, MapPin, Pencil, TriangleAlert, X } from 'lucide-react'
import type { ReactNode } from 'react'

const ICONS = {
  check: Check,
  x: X,
  alert: TriangleAlert,
  chevron: ChevronRight,
  arrow: ArrowRight,
  pin: MapPin,
  copy: Copy,
  external: ExternalLink,
  download: Download,
  edit: Pencil,
  info: Info,
  doc: FileText,
  home: House,
} as const

export type IconName = keyof typeof ICONS

/** 선 아이콘. 한 벌(lucide), 한 크기(16px), 한 굵기(1.5)만 써요. 글자 옆 장식이라 화면 낭독기에는 숨겨요. */
export function Icon({ name }: { name: IconName }): ReactNode {
  const Glyph = ICONS[name]
  return <Glyph className="icon" size={16} strokeWidth={1.5} aria-hidden="true" />
}

/** 지금 일하는 중이라는 표시. 실제로 진행 중일 때만 써요. */
export function Spinner(): ReactNode {
  return <span className="spinner" aria-hidden="true" />
}
