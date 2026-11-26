import { Alert, Button, Divider, Form, Input } from 'antd'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useEffect, useState, type CSSProperties } from 'react'
import { login, register } from '../api/auth'
import { ApiError } from '../api/client'
import { getOidcConfig, type OidcConfig } from '../api/intelligence'
import { useAuth } from '../auth/AuthContext'
import { BrandMark } from '../components/BrandMark'
import { demoMode } from '../demoMode'
import { loginTargetForRole } from '../routes/guards'
import type { CitizenRegisterPayload } from '../types'
import '../styles/login.css'

type DemoRoleKey = 'citizen' | 'agent' | 'department' | 'admin'
type AuthMode = 'login' | 'register'
type RegisterFormValues = CitizenRegisterPayload & { confirm_password: string }

const modeTabsStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
  gap: 4,
  padding: 4,
  borderRadius: 9,
  background: 'var(--ce-shell)',
  border: '1px solid var(--ce-line)',
  marginBottom: 22,
}

const modeTabStyle = (active: boolean): CSSProperties => ({
  height: 36,
  borderRadius: 7,
  border: 'none',
  background: active ? '#ffffff' : 'transparent',
  color: active ? 'var(--ce-ink)' : 'var(--ce-muted)',
  fontFamily: 'var(--ce-font)',
  fontSize: 13.5,
  fontWeight: active ? 600 : 500,
  boxShadow: active ? 'var(--ce-shadow-pill)' : 'none',
  cursor: 'pointer',
  transition: 'all 0.14s ease',
})

function extractApiErrorMessage(err: unknown, fallback: string): string {
  if (!(err instanceof ApiError)) return fallback
  if (err.status === 429) {
    const details = err.details
    if (details && !Array.isArray(details) && typeof details.retry_after === 'number') {
      return `请求过于频繁，请在 ${details.retry_after} 秒后重试`
    }
    return err.message || '请求过于频繁，请稍后重试'
  }
  if ((err.status === 400 || err.status === 422) && Array.isArray(err.details) && err.details.length > 0) {
    const detailMsgs = err.details.map((item) => item?.msg).filter((msg): msg is string => Boolean(msg))
    if (detailMsgs.length > 0) return detailMsgs.join('；')
  }
  return err.message || fallback
}

const ROLE_PROFILES: Record<DemoRoleKey, { label: string; user: string; route: string; title: string; perms: string[] }> = {
  citizen: {
    label: '市民',
    user: 'citizen_local',
    route: '/citizen/chat',
    title: '市民服务空间 · Citizen',
    perms: [
      '对话式诉求建单与结构化草稿编辑',
      '政策知识库 RAG 证据溯源查询',
      '实时跟进本人全部工单与公开答复',
      '满意度确认办结或发起申诉重办',
    ],
  },
  agent: {
    label: '坐席',
    user: 'agent_local',
    route: '/agent/intelligence',
    title: '坐席分诊工作台 · Agent',
    perms: [
      '待受理/已受理队列与键盘高效选单',
      'triage_assistant 智能分诊参考生成',
      '三态人工审核（采纳 / 修订 / 拒绝）留痕',
      '人工受理、派发责任部门与复核办结',
    ],
  },
  department: {
    label: '部门',
    user: 'department_local',
    route: '/department/tickets',
    title: '部门协同工作台 · Department',
    perms: [
      '按办理状态与 SLA 筛选本部门协同任务',
      'handling_assistant 核查清单与回复模板',
      '填写真实办理结果与主办汇总送审',
      '维护本部门政策知识库文档',
    ],
  },
  admin: {
    label: '管理员',
    user: 'admin_local',
    route: '/admin/dashboard',
    title: '运营与治理中心 · Admin',
    perms: [
      '14 日登记趋势、SLA 风险雷达与部门履约',
      '10 类 AI Capability 用量与降级追溯',
      '全链路 audit_logs 审计与申诉重办审批',
      '用户、部门、诉求分类与知识库治理审核',
    ],
  },
}

export function LoginPage() {
  const [form] = Form.useForm<{ username: string; password: string }>()
  const [registerForm] = Form.useForm<RegisterFormValues>()
  const [mode, setMode] = useState<AuthMode>('login')
  const [registerDisabled, setRegisterDisabled] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [oidc, setOidc] = useState<OidcConfig | null>(null)
  const [searchParams] = useSearchParams()
  const demoParam = demoMode ? searchParams.get('demo') : null
  const initialDemo = demoMode && demoParam && Object.hasOwn(ROLE_PROFILES, demoParam) ? demoParam as DemoRoleKey : null
  const [activeRole, setActiveRole] = useState<DemoRoleKey>(initialDemo ?? 'agent')
  const { refresh } = useAuth()
  const nav = useNavigate()
  const location = useLocation()

  useEffect(() => {
    void getOidcConfig().then(setOidc).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (demoMode && initialDemo) {
      setActiveRole(initialDemo)
      form.setFieldValue('username', ROLE_PROFILES[initialDemo].user)
    }
  }, [initialDemo, form])

  const switchMode = (nextMode: AuthMode) => {
    if (mode === nextMode) return
    setMode(nextMode)
    setError('')
  }

  const submit = async (v: { username: string; password: string }) => {
    setBusy(true)
    setError('')
    try {
      await login(v.username, v.password)
      const user = await refresh()
      const requestedPath = (location.state as { from?: { pathname?: string } })?.from?.pathname
      nav(user ? loginTargetForRole(user.role, requestedPath) : '/', { replace: true, state: null })
    } catch (e) {
      setError(extractApiErrorMessage(e, '登录失败，请重试'))
    } finally {
      setBusy(false)
    }
  }

  const submitRegister = async (v: RegisterFormValues) => {
    setBusy(true)
    setError('')
    try {
      await register({
        username: v.username,
        password: v.password,
        display_name: v.display_name,
        phone: v.phone,
      })
      const user = await refresh()
      const requestedPath = (location.state as { from?: { pathname?: string } })?.from?.pathname
      nav(user ? loginTargetForRole(user.role, requestedPath) : '/citizen/chat', { replace: true, state: null })
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        setRegisterDisabled(true)
        setError(e.message || '当前系统已关闭市民自助注册，请联系管理员开通账号')
      } else if (e instanceof ApiError && e.status === 409) {
        setError(e.message || '该用户名已被注册，请更换其他用户名')
      } else {
        setError(extractApiErrorMessage(e, '注册失败，请检查输入信息后重试'))
      }
    } finally {
      setBusy(false)
    }
  }

  const startOidc = () => {
    if (!oidc?.authorization_endpoint || !oidc.client_id || !oidc.redirect_uri) return
    const state = crypto.randomUUID()
    sessionStorage.setItem('tingting_oidc_state', state)
    const query = new URLSearchParams({
      client_id: oidc.client_id,
      redirect_uri: oidc.redirect_uri,
      response_type: 'code',
      scope: oidc.scopes,
      state,
    })
    window.location.assign(`${oidc.authorization_endpoint}?${query}`)
  }

  const selectDemoRole = (role: DemoRoleKey) => {
    if (!demoMode) return
    setActiveRole(role)
    form.setFieldValue('username', ROLE_PROFILES[role].user)
  }

  const profile = demoMode ? ROLE_PROFILES[activeRole] : null

  return (
    <main className="login-shell">
      <div className="login-left">
        <header className="login-masthead">
          <Link to="/welcome" className="login-brand-link">
            <BrandMark size={26} />
            <span>CivicEcho 倾听助手</span>
          </Link>
          <Link className="login-home-link" to="/welcome">返回服务首页</Link>
        </header>

        <section className="login-form-wrap" aria-labelledby="login-heading">
          <div role="tablist" aria-label="账号入口切换" style={modeTabsStyle}>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'login'}
              style={modeTabStyle(mode === 'login')}
              onClick={() => switchMode('login')}
            >
              账号登录
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'register'}
              style={modeTabStyle(mode === 'register')}
              onClick={() => switchMode('register')}
            >
              市民注册
            </button>
          </div>

          {mode === 'login' ? (
            <>
              <h1 id="login-heading">登录倾听助手</h1>
              <p className="login-instruction">使用已分配的账号进入对应角色工作台</p>
              {error && <Alert className="login-error" role="alert" showIcon type="error" title={error} />}
              <Form form={form} layout="vertical" size="large" onFinish={submit} requiredMark={false}>
                <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                  <Input autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder="请输入用户名" />
                </Form.Item>
                <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
                  <Input.Password autoComplete="current-password" placeholder="请输入密码" />
                </Form.Item>
                <Button className="login-submit" type="primary" htmlType="submit" aria-label="安全登录" loading={busy} block>
                  登录
                </Button>
              </Form>

              {oidc?.enabled && (
                <>
                  <Divider plain>或</Divider>
                  <Button block onClick={startOidc}>统一身份认证登录</Button>
                </>
              )}

              {profile && <div className="login-demo-strip">
                <div className="login-demo-head">
                  <span>演示账号快捷填入用户名</span>
                  <span className="workspace-reference">{profile.user}</span>
                </div>
                <div className="login-demo-buttons" role="group" aria-label="选择演示角色">
                  {(Object.keys(ROLE_PROFILES) as DemoRoleKey[]).map((key) => (
                    <button
                      key={key}
                      type="button"
                      className={`login-role-btn${activeRole === key ? ' active' : ''}`}
                      aria-pressed={activeRole === key}
                      onClick={() => selectDemoRole(key)}
                    >
                      {ROLE_PROFILES[key].label}
                    </button>
                  ))}
                </div>
              </div>}
            </>
          ) : (
            <>
              <h1 id="login-heading">注册市民账号</h1>
              <p className="login-instruction">注册后即可在线提交诉求、查看办理进度并参与满意度评价</p>
              {error && <Alert className="login-error" role="alert" showIcon type={registerDisabled ? 'warning' : 'error'} title={error} />}
              {!error && registerDisabled && (
                <Alert
                  className="login-error"
                  role="alert"
                  showIcon
                  type="warning"
                  title="当前系统已关闭市民自助注册，请联系管理员开通账号"
                />
              )}
              <Form form={registerForm} layout="vertical" size="large" onFinish={submitRegister} requiredMark={false}>
                <Form.Item
                  label="用户名"
                  name="username"
                  rules={[
                    { required: true, message: '请输入用户名' },
                    { min: 3, message: '用户名至少 3 个字符' },
                    { max: 64, message: '用户名不能超过 64 个字符' },
                    { pattern: /^[A-Za-z0-9_.-]+$/, message: '用户名仅支持字母、数字、下划线、点或连字符' },
                  ]}
                >
                  <Input autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder="3-64 位字母、数字或 _ . -" />
                </Form.Item>
                <Form.Item
                  label="姓名/昵称（可选）"
                  name="display_name"
                  rules={[{ max: 100, message: '姓名或昵称不能超过 100 个字符' }]}
                >
                  <Input autoComplete="name" placeholder="用于工单联系与评价展示" />
                </Form.Item>
                <Form.Item
                  label="联系电话（可选）"
                  name="phone"
                  rules={[
                    {
                      validator: (_, value?: string) => {
                        const trimmed = value?.trim()
                        if (!trimmed || /^1\d{10}$/.test(trimmed)) return Promise.resolve()
                        return Promise.reject(new Error('请输入 11 位有效手机号'))
                      },
                    },
                  ]}
                >
                  <Input autoComplete="tel" placeholder="11 位手机号（可选）" />
                </Form.Item>
                <Form.Item
                  label="密码"
                  name="password"
                  extra="至少 8 位，且须同时包含字母和数字"
                  rules={[
                    { required: true, message: '请输入密码' },
                    {
                      validator: (_, value?: string) => {
                        if (!value) return Promise.resolve()
                        if (value.length >= 8 && /[A-Za-z]/.test(value) && /\d/.test(value)) {
                          return Promise.resolve()
                        }
                        return Promise.reject(new Error('密码须至少 8 位，且同时包含字母和数字'))
                      },
                    },
                  ]}
                >
                  <Input.Password autoComplete="new-password" placeholder="至少 8 位，包含字母和数字" />
                </Form.Item>
                <Form.Item
                  label="确认密码"
                  name="confirm_password"
                  dependencies={['password']}
                  rules={[
                    { required: true, message: '请再次输入密码' },
                    {
                      validator: (_, value?: string) => {
                        if (!value || registerForm.getFieldValue('password') === value) {
                          return Promise.resolve()
                        }
                        return Promise.reject(new Error('两次输入的密码不一致'))
                      },
                    },
                  ]}
                >
                  <Input.Password autoComplete="new-password" placeholder="请再次输入密码" />
                </Form.Item>
                <Button
                  className="login-submit"
                  type="primary"
                  htmlType="submit"
                  aria-label="注册并登录"
                  disabled={registerDisabled}
                  loading={busy}
                  block
                >
                  注册并登录
                </Button>
              </Form>
            </>
          )}
        </section>

        <footer className="login-foot">
          <Link className="login-home-link" to="/chat">访客智能对话 →</Link>
        </footer>
      </div>

      <aside className="login-showcase" aria-hidden="true">
        <div className="login-showcase-glow" />
        {profile && <div className="login-showcase-top">
          <span>AUTHORIZATION POLICY · RBAC</span>
          <span><span className="ce-status-dot tone-ok" style={{ marginRight: 6 }} />Demo Environment</span>
        </div>}

        <div className="login-showcase-center">
          {profile && <div className="login-policy-card">
            <div className="login-policy-head">
              <strong>{profile.title}</strong>
              <span className="login-policy-route">{profile.route}</span>
            </div>
            <ul className="login-policy-list">
              {profile.perms.map((perm) => (
                <li key={perm}>
                  <span className="ce-status-dot tone-ok" />
                  <span>{perm}</span>
                </li>
              ))}
            </ul>
            <div className="login-policy-foot">
              <span>account: {profile.user}</span>
              <span>advisory_only: true</span>
            </div>
          </div>}
          <p className="login-tagline">
            克制、透明、可追溯的
            <span>现代政务诉求协同底座。</span>
          </p>
        </div>

        {profile && <div className="login-showcase-bottom">
          <span>CivicEcho Design System</span>
          <span>Backend-Enforced Permissions</span>
        </div>}
      </aside>
    </main>
  )
}
