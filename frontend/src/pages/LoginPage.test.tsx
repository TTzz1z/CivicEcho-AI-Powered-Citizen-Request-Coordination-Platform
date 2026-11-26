import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { register } from '../api/auth'
import { ApiError } from '../api/client'
import { renderApp } from '../test/render'
import { LoginPage } from './LoginPage'

const mockRefresh = vi.fn()

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ refresh: mockRefresh, user: null }),
}))
vi.mock('../api/auth', () => ({
  login: vi.fn(),
  register: vi.fn(),
}))
vi.mock('../api/intelligence', () => ({
  getOidcConfig: vi.fn().mockResolvedValue({ enabled: false }),
}))
vi.mock('../demoMode', () => ({ demoMode: false }))

const mockedRegister = vi.mocked(register)

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('validates required credentials', async () => {
    renderApp(<MemoryRouter><LoginPage /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: '安全登录' }))
    expect(await screen.findByText('请输入用户名')).toBeInTheDocument()
    expect(screen.getByText('请输入密码')).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 30))
  })

  it('ignores demo links and shortcuts in production mode while keeping citizen registration available', async () => {
    const user = userEvent.setup()
    renderApp(<MemoryRouter initialEntries={['/login?demo=admin']}><LoginPage /></MemoryRouter>)
    expect(screen.getByLabelText('用户名')).toHaveValue('')
    expect(screen.queryByText('演示账号快捷填入用户名')).not.toBeInTheDocument()

    const registerTab = screen.getByRole('tab', { name: '市民注册' })
    expect(registerTab).toBeInTheDocument()
    await user.click(registerTab)
    expect(screen.getByRole('heading', { name: '注册市民账号' })).toBeInTheDocument()
    expect(screen.getByText('至少 8 位，且须同时包含字母和数字')).toBeInTheDocument()
  })

  it('validates citizen registration fields including strong password and confirmation', async () => {
    const user = userEvent.setup()
    renderApp(<MemoryRouter><LoginPage /></MemoryRouter>)
    await user.click(screen.getByRole('tab', { name: '市民注册' }))

    await user.type(screen.getByLabelText('用户名'), 'ab')
    await user.type(screen.getByLabelText('联系电话（可选）'), '12345')
    await user.type(screen.getByLabelText('密码'), 'onlyletters')
    await user.type(screen.getByLabelText('确认密码'), 'different1')
    await user.click(screen.getByRole('button', { name: '注册并登录' }))

    expect(await screen.findByText('用户名至少 3 个字符')).toBeInTheDocument()
    expect(await screen.findByText('请输入 11 位有效手机号')).toBeInTheDocument()
    expect(await screen.findByText('密码须至少 8 位，且同时包含字母和数字')).toBeInTheDocument()
    expect(await screen.findByText('两次输入的密码不一致')).toBeInTheDocument()
    expect(mockedRegister).not.toHaveBeenCalled()
  })

  it('submits citizen registration without role and navigates to citizen workspace', async () => {
    const user = userEvent.setup()
    mockedRegister.mockResolvedValue({
      access_token: 'tok-citizen-1',
      token_type: 'bearer',
    })
    mockRefresh.mockResolvedValue({
      id: 42,
      username: 'citizen_new',
      display_name: '林市民',
      role: 'citizen',
      is_active: true,
    })

    renderApp(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/citizen/chat" element={<div>市民对话首页</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('tab', { name: '市民注册' }))
    await user.type(screen.getByLabelText('用户名'), 'citizen_new')
    await user.type(screen.getByLabelText('姓名/昵称（可选）'), '林市民')
    await user.type(screen.getByLabelText('联系电话（可选）'), '13800138000')
    await user.type(screen.getByLabelText('密码'), 'Civic2026a')
    await user.type(screen.getByLabelText('确认密码'), 'Civic2026a')
    await user.click(screen.getByRole('button', { name: '注册并登录' }))

    await waitFor(() => {
      expect(mockedRegister).toHaveBeenCalledWith({
        username: 'citizen_new',
        password: 'Civic2026a',
        display_name: '林市民',
        phone: '13800138000',
      })
    })
    const calledPayload = mockedRegister.mock.calls[0][0] as unknown as Record<string, unknown>
    expect(calledPayload).not.toHaveProperty('role')
    expect(mockRefresh).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('市民对话首页')).toBeInTheDocument()
  })

  it('handles 409 duplicate username, 429 rate limit, and 403 disabled registration errors', async () => {
    const user = userEvent.setup()
    renderApp(<MemoryRouter><LoginPage /></MemoryRouter>)
    await user.click(screen.getByRole('tab', { name: '市民注册' }))

    await user.type(screen.getByLabelText('用户名'), 'citizen_dup')
    await user.type(screen.getByLabelText('密码'), 'Civic2026a')
    await user.type(screen.getByLabelText('确认密码'), 'Civic2026a')

    mockedRegister.mockRejectedValueOnce(new ApiError(409, 'USERNAME_EXISTS', '该用户名已被注册'))
    await user.click(screen.getByRole('button', { name: '注册并登录' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('该用户名已被注册')

    mockedRegister.mockRejectedValueOnce(new ApiError(429, 'RATE_LIMITED', '请求过多', { retry_after: 45 }))
    await user.click(screen.getByRole('button', { name: '注册并登录' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('请在 45 秒后重试')

    mockedRegister.mockRejectedValueOnce(new ApiError(403, 'REGISTRATION_DISABLED', '当前系统已关闭市民自助注册'))
    await user.click(screen.getByRole('button', { name: '注册并登录' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('当前系统已关闭市民自助注册')
    expect(screen.getByRole('button', { name: '注册并登录' })).toBeDisabled()
  })
})
