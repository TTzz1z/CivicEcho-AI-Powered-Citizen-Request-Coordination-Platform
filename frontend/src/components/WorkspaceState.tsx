import { Alert, Button, Empty, Skeleton } from 'antd'
import { ApiError } from '../api/client'

export function WorkspaceLoading({ label }: { label: string }) {
  return <div role="status" aria-label={label} aria-busy="true"><Skeleton active paragraph={{ rows: 3 }} /></div>
}

export function WorkspaceEmpty({ text }: { text: string }) {
  return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={text} className="workspace-empty" />
}

export function WorkspaceError({ error, fallback, retry }: { error: unknown; fallback: string; retry?: () => void }) {
  return <Alert showIcon type="error" title={error instanceof ApiError ? error.message : fallback}
    action={retry && <Button size="small" onClick={retry}>重试</Button>} />
}
