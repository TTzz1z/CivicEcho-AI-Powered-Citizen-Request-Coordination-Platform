import { Alert, Card, Spin } from 'antd'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { exchangeOidcCode, getOidcConfig } from '../api/intelligence'
import { tokenStore } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { loginTargetForRole } from '../routes/guards'
import '../styles/login.css'

class OidcCallbackError extends Error {}

async function getCallbackToken(params: URLSearchParams) {
  const expected = sessionStorage.getItem('tingting_oidc_state')
  sessionStorage.removeItem('tingting_oidc_state')
  const state = params.get('state')
  if (!state || !expected || state !== expected) {
    throw new OidcCallbackError('登录请求已失效，请返回登录页重试。')
  }
  if (params.has('error')) throw new OidcCallbackError('身份认证未完成，请重新登录。')
  const code = params.get('code')
  if (!code) throw new OidcCallbackError('身份认证未返回授权码，请重新登录。')
  const config = await getOidcConfig()
  if (!config.enabled || !config.redirect_uri) {
    throw new OidcCallbackError('统一身份认证暂不可用，请返回登录页。')
  }
  const result = await exchangeOidcCode(code, config.redirect_uri)
  return result.access_token
}

export function OidcCallbackPage() {
  const [params] = useSearchParams()
  const [error, setError] = useState('')
  const { refresh } = useAuth()
  const refreshUser = useRef(refresh)
  const exchange = useRef<{ query: string; token: Promise<string> }>()
  const navigate = useNavigate()

  useEffect(() => { refreshUser.current = refresh }, [refresh])
  useEffect(() => {
    let active = true
    const query = params.toString()
    if (!exchange.current || exchange.current.query !== query) {
      exchange.current = { query, token: getCallbackToken(params) }
    }
    void exchange.current.token.then(async token => {
      if (!active) return
      tokenStore.set(token)
      const user = await refreshUser.current()
      if (!active) return
      if (!user) {
        if (tokenStore.get() === token) tokenStore.clear()
        throw new OidcCallbackError('暂时无法加载登录账号，请重新登录。')
      }
      navigate(loginTargetForRole(user.role), { replace: true })
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof OidcCallbackError ? reason.message : '统一身份认证暂时失败，请重新登录。')
    })
    return () => { active = false }
  }, [navigate, params])

  return <main className="login-callback-shell">
    <Card className="surface login-callback-card">
      <h1>统一身份认证</h1>
      {error ? <>
        <Alert type="error" showIcon title={error} role="alert" />
        <div className="login-callback-actions"><Link to="/login" replace>返回登录</Link></div>
      </> : <div role="status"><Spin size="small" /> 正在完成统一身份认证</div>}
    </Card>
  </main>
}
