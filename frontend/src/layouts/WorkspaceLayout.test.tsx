import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { changePassword } from '../api/auth'
import { ApiError } from '../api/client'
import { menuByRole, WorkspaceLayout } from '../layouts/WorkspaceLayout'
import { renderApp } from '../test/render'
import { closureTypeLabel } from '../utils/closureType'

const mockRefresh = vi.fn()
const mockLogout = vi.fn()

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 7,
      username: 'citizen_local',
      display_name: '测试市民',
      role: 'citizen' as const,
      is_active: true,
    },
    loading: false,
    refresh: mockRefresh,
    logout: mockLogout,
  }),
}))

vi.mock('../api/auth', () => ({
  changePassword: vi.fn(),
}))

vi.mock('../components/WorkspaceNotifications', () => ({
  WorkspaceNotifications: () => <div data-testid="workspace-notifications-stub" />,
}))

const mockedChangePassword = vi.mocked(changePassword)

describe('admin menu naming', () => {
  it('keeps distinct governance vs document maintenance entries', () => {
    const labels = menuByRole.admin.map((item) => item.label)
    expect(labels).toContain('知识库治理审核')
    expect(labels).toContain('部门文档维护')
    expect(labels).not.toContain('AI 知识库')
    expect(labels).not.toContain('文档管理')
    const governance = menuByRole.admin.find((item) => item.label === '知识库治理审核')
    const docs = menuByRole.admin.find((item) => item.label === '部门文档维护')
    expect(governance?.key).toBe('/admin/kb')
    expect(docs?.key).toBe('/department/kb')
  })
})

describe('closureTypeLabel', () => {
  it('maps all supported closure types including phone follow-up', () => {
    expect(closureTypeLabel('citizen_confirmed')).toBe('市民确认')
    expect(closureTypeLabel('phone_confirmed')).toBe('电话回访确认')
    expect(closureTypeLabel('admin_override')).toBe('管理员代办结')
    expect(closureTypeLabel(null)).toBe('—')
    expect(closureTypeLabel(undefined)).toBe('—')
  })

  it('does not render phone follow-up closure as unknown', () => {
    expect(closureTypeLabel('phone_confirmed')).not.toMatch(/未知/)
    expect(closureTypeLabel('phone_confirmed')).not.toBe('—')
  })
})

describe('WorkspaceLayout change password modal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  function renderLayout() {
    return renderApp(
      <MemoryRouter initialEntries={['/citizen/tickets']}>
        <Routes>
          <Route element={<WorkspaceLayout />}>
            <Route path="/citizen/tickets" element={<div>我的工单内容</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  it('opens change password modal from account menu and validates inputs', async () => {
    const user = userEvent.setup({ delay: null })
    renderLayout()

    await user.click(screen.getByRole('button', { name: /测试市民.*账号菜单/ }))
    expect(await screen.findByText('切换账号')).toBeInTheDocument()
    expect(screen.getByText('退出登录')).toBeInTheDocument()

    await user.click(screen.getByText('修改密码'))
    expect(await screen.findByRole('dialog', { name: '修改密码' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'OldPass123' } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'OldPass123' } })
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'Mismatch99' } })
    await user.click(screen.getByRole('button', { name: '确认修改' }))

    expect(await screen.findByText('新密码不能与当前密码相同')).toBeInTheDocument()
    expect(await screen.findByText('两次输入的新密码不一致')).toBeInTheDocument()
    expect(mockedChangePassword).not.toHaveBeenCalled()
  })

  it('submits password change, refreshes session, and displays backend errors inline', async () => {
    const user = userEvent.setup({ delay: null })
    renderLayout()

    await user.click(screen.getByRole('button', { name: /测试市民.*账号菜单/ }))
    await user.click(await screen.findByText('修改密码'))
    await screen.findByRole('dialog', { name: '修改密码' })

    mockedChangePassword.mockRejectedValueOnce(new ApiError(400, 'INVALID_CURRENT_PASSWORD', '当前密码不正确'))
    fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'WrongPass1' } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'NewCivic2026' } })
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'NewCivic2026' } })
    await user.click(screen.getByRole('button', { name: '确认修改' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('当前密码不正确')
    expect(screen.getByRole('dialog', { name: '修改密码' })).toBeInTheDocument()

    mockedChangePassword.mockResolvedValueOnce({
      access_token: 'rotated-token-2',
      token_type: 'bearer',
      token_version: 2,
    })
    mockRefresh.mockResolvedValueOnce({
      id: 7,
      username: 'citizen_local',
      display_name: '测试市民',
      role: 'citizen',
      is_active: true,
    })

    fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'OldCivic2025' } })
    await user.click(screen.getByRole('button', { name: '确认修改' }))

    await waitFor(() => {
      expect(mockedChangePassword).toHaveBeenLastCalledWith({
        current_password: 'OldCivic2025',
        new_password: 'NewCivic2026',
      })
    })
    expect(mockRefresh).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '修改密码' })).not.toBeInTheDocument()
    })
  })
})
