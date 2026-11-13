import { useLayoutEffect, useRef, useState } from 'react'

/** 요소의 실제 너비를 재요. 차트는 이 너비에 맞춰 1:1 로 그려서 글자가 뭉개지지 않아요. */
export function useWidth<T extends HTMLElement>(fallback: number): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(fallback)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = (): void => {
      const w = el.getBoundingClientRect().width
      if (w > 0) setWidth(Math.round(w))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}
