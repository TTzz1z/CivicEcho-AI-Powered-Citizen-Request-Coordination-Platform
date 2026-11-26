import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppErrorBoundary } from './AppErrorBoundary'

function BrokenChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('SECRET_INTERNAL_STACK_TOKEN_XYZ')
  }
  return <div>正常业务内容</div>
}

describe('AppErrorBoundary', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('renders normal children when no rendering error occurs', () => {
    render(
      <AppErrorBoundary>
        <BrokenChild shouldThrow={false} />
      </AppErrorBoundary>,
    )
    expect(screen.getByText('正常业务内容')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('catches render crash, shows gov-style recovery card, and hides raw error text from DOM', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <AppErrorBoundary>
        <BrokenChild shouldThrow />
      </AppErrorBoundary>,
    )

    const alert = screen.getByRole('alert')
    expect(alert).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '系统界面遇到意外异常' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试当前页' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '返回工作台' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新应用' })).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('SECRET_INTERNAL_STACK_TOKEN_XYZ')
    expect(consoleSpy).toHaveBeenCalled()
  })

  it('recovers when clicking 重试当前页 and invokes onRetry', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const user = userEvent.setup()
    const onRetry = vi.fn()
    let fail = true

    function ToggleChild() {
      if (fail) throw new Error('boom')
      return <div>已恢复正常视图</div>
    }

    render(
      <AppErrorBoundary onRetry={onRetry}>
        <ToggleChild />
      </AppErrorBoundary>,
    )

    expect(screen.getByRole('alert')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: '重试当前页' }))

    expect(onRetry).toHaveBeenCalledTimes(1)
    expect(screen.getByText('已恢复正常视图')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('handles 返回工作台 and 刷新应用 via callbacks and default window.location', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const user = userEvent.setup()
    const onGoHome = vi.fn()
    const onReload = vi.fn()

    const { unmount } = render(
      <AppErrorBoundary onGoHome={onGoHome} onReload={onReload}>
        <BrokenChild shouldThrow />
      </AppErrorBoundary>,
    )

    await user.click(screen.getByRole('button', { name: '返回工作台' }))
    await user.click(screen.getByRole('button', { name: '刷新应用' }))
    expect(onGoHome).toHaveBeenCalledTimes(1)
    expect(onReload).toHaveBeenCalledTimes(1)
    unmount()

    const assign = vi.fn()
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign, reload })

    render(
      <AppErrorBoundary>
        <BrokenChild shouldThrow />
      </AppErrorBoundary>,
    )

    await user.click(screen.getByRole('button', { name: '返回工作台' }))
    await user.click(screen.getByRole('button', { name: '刷新应用' }))
    expect(assign).toHaveBeenCalledWith('/')
    expect(reload).toHaveBeenCalledTimes(1)
  })
})
