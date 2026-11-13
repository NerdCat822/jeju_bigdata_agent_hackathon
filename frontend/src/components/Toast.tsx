import { useEffect } from 'react'
import type { ReactNode } from 'react'
import type { Notice } from '../state/agent'
import { Icon } from './Icon'

/** 화면 아래에 잠깐 뜨는 안내. */
export function Toast({ notice, onClose }: { notice: Notice | null; onClose: () => void }): ReactNode {
  useEffect(() => {
    if (!notice) return
    const id = window.setTimeout(onClose, 7000)
    return () => window.clearTimeout(id)
  }, [notice, onClose])
  if (!notice) return null
  return (
    <div className={`toast is-${notice.tone}`} role={notice.tone === 'warn' ? 'alert' : 'status'}>
      <Icon name={notice.tone === 'warn' ? 'alert' : 'info'} />
      <span>{notice.text}</span>
      <button type="button" className="icon-button" aria-label="안내 닫기" onClick={onClose}>
        <Icon name="x" size={14} />
      </button>
    </div>
  )
}
