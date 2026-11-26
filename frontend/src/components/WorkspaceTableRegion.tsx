import { useRef, type ReactNode } from 'react'

export function WorkspaceTableRegion({ label, children }: { label: string; children: ReactNode }) {
  const region = useRef<HTMLDivElement>(null)
  return <div ref={region} className="workspace-scroll-region" role="region" aria-label={label} tabIndex={0}
    onKeyDown={(event) => {
      if (event.target !== region.current || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return
      const scrollable = region.current?.querySelector<HTMLElement>('.ant-table-content') ?? region.current
      if (!scrollable || scrollable.scrollWidth <= scrollable.clientWidth) return
      event.preventDefault()
      scrollable.scrollBy({ left: event.key === 'ArrowLeft' ? -80 : 80 })
    }}>{children}</div>
}
