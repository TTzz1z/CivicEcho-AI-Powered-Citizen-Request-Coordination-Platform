import { Alert, Button } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

type Health = { success: boolean; data?: { status?: string }; error?: { code?: string } }

async function probeService() {
  const response = await fetch('/api/v1/system/health', { signal: AbortSignal.timeout(4_000), cache: 'no-store' })
  const payload = await response.json() as Health
  if (response.ok && payload.success && payload.data?.status === 'ready') return 'ready'
  return payload.error?.code === 'OBJECT_STORAGE_UNAVAILABLE' ? 'storage' : 'unavailable'
}

export function ServiceStatus() {
  const [offline, setOffline] = useState(() => !navigator.onLine)
  useEffect(() => {
    const updateConnection = () => setOffline(!navigator.onLine)
    window.addEventListener('online', updateConnection)
    window.addEventListener('offline', updateConnection)
    return () => {
      window.removeEventListener('online', updateConnection)
      window.removeEventListener('offline', updateConnection)
    }
  }, [])

  const query = useQuery({
    queryKey: ['service-status'],
    queryFn: probeService,
    refetchInterval: 30_000,
    retry: false,
    enabled: !offline,
  })

  if (!offline && !query.isError && (!query.data || query.data === 'ready')) return null
  const title = offline ? '当前设备已离线'
    : query.data === 'storage' && !query.isError ? '附件和文档服务暂不可用'
    : '暂时无法连接办理服务'

  return <Alert role="status" banner showIcon type="warning" title={title}
    description={offline ? '联网后将自动检查服务。若刚才已提交，请在恢复后先查看办理结果。'
      : '系统会定期重新检查。若刚才已提交，请先确认结果再重试。'}
    action={!offline && <Button size="small" loading={query.isFetching} onClick={() => void query.refetch()}>重新检查</Button>}
  />
}
