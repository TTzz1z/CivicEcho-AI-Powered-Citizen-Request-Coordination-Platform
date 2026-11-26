import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Spin } from 'antd'
import type { EChartsCoreOption } from 'echarts/core'

export function ChartPanel({ option, label, empty = false }: { option: EChartsCoreOption; label: string; empty?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error' | 'load-error'>('loading')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const element = ref.current
    if (!element || empty) return
    setStatus('loading')
    let disposed = false
    let chart: { resize: () => void; dispose: () => void } | undefined

    void import('../charts/runtime').then(({ echarts }) => {
      if (disposed) return
      const instance = echarts.init(element)
      chart = instance
      instance.setOption(option)
      setStatus('ready')
    }, () => {
      if (!disposed) setStatus('load-error')
    }).catch(() => {
      if (disposed) return
      chart?.dispose()
      chart = undefined
      setStatus('error')
    })

    const observer = new ResizeObserver(() => chart?.resize())
    observer.observe(element)
    return () => {
      disposed = true
      observer.disconnect()
      chart?.dispose()
    }
  }, [option, empty, attempt])

  if (empty) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可展示数据" />
  const failed = status === 'error' || status === 'load-error'
  return <div style={{ position: 'relative' }}>
    {status === 'loading' && <div className="chart-loading" role="status"><Spin /> 图表加载中</div>}
    {failed && <Alert type="warning" showIcon title="图表暂时无法显示" action={
      status === 'load-error'
        ? <Button size="small" onClick={() => window.location.reload()}>重新加载页面</Button>
        : <Button size="small" onClick={() => setAttempt(value => value + 1)}>重试</Button>
    } />}
    <div ref={ref} className="chart" role="img" aria-label={label} hidden={failed} />
  </div>
}
