import { Component, Fragment, type CSSProperties, type ErrorInfo, type ReactNode } from 'react'

export interface AppErrorBoundaryProps {
  children: ReactNode
  onRetry?: () => void
  onGoHome?: () => void
  onReload?: () => void
}

interface AppErrorBoundaryState {
  hasError: boolean
  retryKey: number
}

const shellStyle: CSSProperties = {
  minHeight: '100dvh',
  display: 'grid',
  placeItems: 'center',
  padding: '24px 16px',
  background: 'var(--ce-shell, #f4f5f7)',
  color: 'var(--ce-ink, #09090b)',
  fontFamily: 'var(--ce-font, system-ui, sans-serif)',
}

const cardStyle: CSSProperties = {
  margin: '0 auto',
  width: 'min(100%, 560px)',
  background: 'var(--ce-paper, #ffffff)',
  border: '1px solid var(--ce-line, rgba(9, 9, 11, 0.08))',
  borderRadius: 'var(--ce-radius-lg, 12px)',
  boxShadow: 'var(--ce-shadow-elevated, 0 24px 64px -16px rgba(9, 9, 11, 0.12))',
  padding: '40px 32px',
  textAlign: 'center',
}

const badgeStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  padding: '4px 12px',
  borderRadius: 999,
  background: 'rgba(225, 29, 72, 0.08)',
  color: 'var(--ce-danger, #e11d48)',
  fontFamily: 'var(--ce-mono, monospace)',
  fontSize: 12,
  fontWeight: 600,
  letterSpacing: '0.02em',
  marginBottom: 18,
}

const dotStyle: CSSProperties = {
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: 'var(--ce-danger, #e11d48)',
  display: 'inline-block',
}

const headingStyle: CSSProperties = {
  margin: '0 0 12px',
  fontSize: 22,
  fontWeight: 650,
  lineHeight: 1.35,
  letterSpacing: '-0.02em',
  color: 'var(--ce-ink, #09090b)',
}

const bodyStyle: CSSProperties = {
  margin: '0 0 28px',
  fontSize: 14,
  lineHeight: 1.65,
  color: 'var(--ce-muted, #52525b)',
}

const actionsStyle: CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  justifyContent: 'center',
  gap: 10,
}

const baseButtonStyle: CSSProperties = {
  minHeight: 38,
  padding: '0 16px',
  borderRadius: 8,
  border: '1px solid var(--ce-line-strong, rgba(9, 9, 11, 0.14))',
  background: '#ffffff',
  color: 'var(--ce-ink, #09090b)',
  fontSize: 13.5,
  fontWeight: 550,
  fontFamily: 'inherit',
  cursor: 'pointer',
}

const primaryButtonStyle: CSSProperties = {
  ...baseButtonStyle,
  background: 'var(--ce-primary, #09090b)',
  borderColor: 'var(--ce-primary, #09090b)',
  color: '#ffffff',
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false,
    retryKey: 0,
  }

  static getDerivedStateFromError(): Partial<AppErrorBoundaryState> {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[AppErrorBoundary]', error.name, info.componentStack)
  }

  private handleRetry = (): void => {
    this.props.onRetry?.()
    this.setState((prev) => ({
      hasError: false,
      retryKey: prev.retryKey + 1,
    }))
  }

  private handleGoHome = (): void => {
    if (this.props.onGoHome) {
      this.props.onGoHome()
      return
    }
    window.location.assign('/')
  }

  private handleReload = (): void => {
    if (this.props.onReload) {
      this.props.onReload()
      return
    }
    window.location.reload()
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <main style={shellStyle}>
          <section className="surface error-card" role="alert" aria-labelledby="app-error-heading" style={cardStyle}>
            <div style={badgeStyle}>
              <span aria-hidden="true" style={dotStyle} />
              <span>CIVICECHO · 系统运行保护</span>
            </div>
            <h1 id="app-error-heading" style={headingStyle}>
              系统界面遇到意外异常
            </h1>
            <p style={bodyStyle}>
              当前页面渲染发生意外中断，您已提交或保存的数据不会受到影响。请尝试恢复当前视图或返回工作台。
            </p>
            <div style={actionsStyle}>
              <button type="button" style={primaryButtonStyle} onClick={this.handleRetry}>
                重试当前页
              </button>
              <button type="button" style={baseButtonStyle} onClick={this.handleGoHome}>
                返回工作台
              </button>
              <button type="button" style={baseButtonStyle} onClick={this.handleReload}>
                刷新应用
              </button>
            </div>
          </section>
        </main>
      )
    }

    return <Fragment key={this.state.retryKey}>{this.props.children}</Fragment>
  }
}
