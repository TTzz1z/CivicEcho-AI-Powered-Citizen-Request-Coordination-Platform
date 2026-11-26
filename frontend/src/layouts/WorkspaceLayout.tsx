import { cloneElement, isValidElement, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Alert, Avatar, Button, Drawer, Dropdown, Form, Grid, Input, Layout, Menu, Modal, message } from 'antd'
import {
  ApartmentOutlined, AuditOutlined, BellOutlined, BookOutlined, BulbOutlined, CommentOutlined,
  CustomerServiceOutlined, DashboardOutlined, DatabaseOutlined, DownOutlined, HomeOutlined,
  LockOutlined, LogoutOutlined, MenuUnfoldOutlined, SafetyOutlined, SearchOutlined, SwapOutlined, TeamOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { changePassword } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { BrandMark } from '../components/BrandMark'
import { WorkspaceNotifications } from '../components/WorkspaceNotifications'
import type { Role } from '../types'

const { Header, Sider, Content } = Layout

const roleLabels: Record<Role, string> = {
  citizen: '市民', agent: '坐席', department_staff: '部门人员', admin: '管理员',
}
const workspaceLabels: Record<Role, string> = {
  citizen: '市民服务', agent: '坐席工作台', department_staff: '部门办理', admin: '运营管理',
}

/** 侧栏菜单：管理员「知识库治理审核」与「部门文档维护」职责不同，均保留入口 */
export const menuByRole: Record<Role, { key: string; icon: React.ReactNode; label: string }[]> = {
  citizen: [
    { key: '/citizen/chat', icon: <CommentOutlined />, label: '智能对话' },
    { key: '/citizen/policy', icon: <BookOutlined />, label: '政策咨询' },
    { key: '/citizen/tickets', icon: <UnorderedListOutlined />, label: '我的工单' },
    { key: '/citizen/intelligence', icon: <BulbOutlined />, label: '智能诉求检查' },
    { key: '/citizen/notifications', icon: <BellOutlined />, label: '通知中心' },
    { key: '/citizen/aftercare', icon: <CustomerServiceOutlined />, label: '回访与申诉' },
  ],
  agent: [
    { key: '/agent/tickets', icon: <UnorderedListOutlined />, label: '待办与工单' },
    { key: '/agent/policy', icon: <BookOutlined />, label: '政策辅助' },
    { key: '/agent/intelligence', icon: <BulbOutlined />, label: '智能分诊与派发' },
    { key: '/agent/notifications', icon: <BellOutlined />, label: '通知中心' },
    { key: '/agent/aftercare', icon: <CustomerServiceOutlined />, label: '回访与申诉' },
  ],
  department_staff: [
    { key: '/department/tickets', icon: <UnorderedListOutlined />, label: '部门工单' },
    { key: '/department/kb', icon: <DatabaseOutlined />, label: '政策知识库' },
    { key: '/department/intelligence', icon: <BulbOutlined />, label: 'AI 办件与文书' },
    { key: '/department/notifications', icon: <BellOutlined />, label: '通知中心' },
    { key: '/department/aftercare', icon: <CustomerServiceOutlined />, label: '回访与申诉' },
  ],
  admin: [
    { key: '/admin/dashboard', icon: <DashboardOutlined />, label: '运营总览' },
    { key: '/admin/tickets', icon: <UnorderedListOutlined />, label: '工单查询' },
    { key: '/admin/kb', icon: <DatabaseOutlined />, label: '知识库治理审核' },
    { key: '/department/kb', icon: <DatabaseOutlined />, label: '部门文档维护' },
    { key: '/admin/ai-usage', icon: <SafetyOutlined />, label: 'AI 用量与安全' },
    { key: '/admin/intelligence', icon: <BulbOutlined />, label: '智能与平台接入' },
    { key: '/admin/notifications', icon: <BellOutlined />, label: '通知中心' },
    { key: '/admin/aftercare', icon: <CustomerServiceOutlined />, label: '回访与申诉' },
    { key: '/admin/categories', icon: <ApartmentOutlined />, label: '诉求分类' },
    { key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' },
    { key: '/admin/departments', icon: <HomeOutlined />, label: '部门管理' },
    { key: '/admin/audit', icon: <AuditOutlined />, label: '审计日志' },
  ],
}

export function WorkspaceLayout() {
  const { user, logout, refresh } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const screens = Grid.useBreakpoint()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [cmdOpen, setCmdOpen] = useState(false)
  const [cmdQuery, setCmdQuery] = useState('')
  const [cmdIndex, setCmdIndex] = useState(-1)
  const [pwOpen, setPwOpen] = useState(false)
  const [pwBusy, setPwBusy] = useState(false)
  const [pwError, setPwError] = useState('')
  const [pwForm] = Form.useForm<{ current_password: string; new_password: string; confirm_password: string }>()
  const cmdInvoker = useRef<HTMLElement | null>(null)
  const commandList = useRef<HTMLDivElement | null>(null)
  const openCommands = useCallback(() => {
    cmdInvoker.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setCmdQuery('')
    setCmdIndex(-1)
    setCmdOpen(true)
  }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.repeat && !event.isComposing && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        if (cmdOpen) setCmdOpen(false)
        else openCommands()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [cmdOpen, openCommands])

  const items = useMemo(() => (user ? menuByRole[user.role] : []), [user])
  const filteredCmd = useMemo(() => {
    const q = cmdQuery.trim().toLowerCase()
    if (!q) return items
    return items.filter((item) => item.label.toLowerCase().includes(q) || item.key.toLowerCase().includes(q))
  }, [items, cmdQuery])

  useEffect(() => {
    if (cmdIndex < 0) return
    commandList.current?.children[cmdIndex]?.scrollIntoView({ block: 'nearest' })
  }, [cmdIndex])

  const goToCommand = (path: string) => {
    navigate(path)
    setCmdOpen(false)
  }

  function handleCommandKeys(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing || !filteredCmd.length) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const count = filteredCmd.length
      setCmdIndex(index => {
        if (index < 0) return event.key === 'ArrowDown' ? 0 : count - 1
        const step = event.key === 'ArrowDown' ? 1 : -1
        return (index + step + count) % count
      })
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      const selected = filteredCmd[Math.max(cmdIndex, 0)]
      if (selected) goToCommand(selected.key)
    }
  }

  if (!user) return null

  const active = items.find(({ key }) => pathname === key || pathname.startsWith(`${key}/`))
  const workspace = workspaceLabels[user.role]
  const leave = () => {
    logout()
    navigate('/login', { replace: true, state: null })
  }

  const openChangePassword = () => {
    pwForm.resetFields()
    setPwError('')
    setPwOpen(true)
  }

  const closeChangePassword = () => {
    setPwOpen(false)
    setPwError('')
    pwForm.resetFields()
  }

  const submitChangePassword = async (values: { current_password: string; new_password: string; confirm_password: string }) => {
    setPwBusy(true)
    setPwError('')
    try {
      await changePassword({
        current_password: values.current_password,
        new_password: values.new_password,
      })
      await refresh()
      message.success('密码已修改，当前会话凭据已更新')
      closeChangePassword()
    } catch (e) {
      if (e instanceof ApiError && Array.isArray(e.details) && e.details.length > 0) {
        const detailMsgs = e.details.map((item) => item?.msg).filter((msg): msg is string => Boolean(msg))
        setPwError(detailMsgs.length > 0 ? detailMsgs.join('；') : e.message)
      } else {
        setPwError(e instanceof ApiError ? e.message : '修改密码失败，请重试')
      }
    } finally {
      setPwBusy(false)
    }
  }

  const navigation = (
    <nav aria-label={workspace} className="workspace-navigation">
      <Menu
        mode="inline"
        inlineIndent={10}
        selectedKeys={active ? [active.key] : []}
        items={items.map((item) => ({
          ...item,
          icon: isValidElement<{ 'aria-hidden'?: boolean }>(item.icon)
            ? cloneElement(item.icon, { 'aria-hidden': true })
            : item.icon,
        }))}
        onClick={({ key }) => {
          navigate(key)
          setDrawerOpen(false)
        }}
      />
    </nav>
  )

  return (
    <Layout className={`civic-workspace workspace-${user.role}`}>
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      {screens.lg && (
        <Sider className="app-sider" width={212} trigger={null}>
          <div className="brand">
            <BrandMark size={24} />
            <div className="brand-copy">
              <span className="brand-title">倾听助手</span>
              <span className="brand-role-chip">{roleLabels[user.role]}</span>
            </div>
          </div>
          <div className="workspace-cmd-wrap">
            <button
              type="button"
              className="workspace-cmd-trigger"
              onClick={openCommands}
              aria-label="打开快捷导航命令面板"
            >
              <span className="workspace-cmd-placeholder"><SearchOutlined aria-hidden /> 快捷跳转…</span>
              <kbd className="ce-kbd">{/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘K' : 'Ctrl+K'}</kbd>
            </button>
          </div>
          <div className="workspace-nav-label">{workspace}</div>
          {navigation}
        </Sider>
      )}
      {!screens.lg && (
        <Drawer
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          title={workspace}
          size={264}
          className="workspace-drawer"
          styles={{ body: { padding: '8px 0' } }}
        >
          {navigation}
        </Drawer>
      )}
      <div className="workspace-sheet-frame">
        <Layout className="workspace-main workspace-sheet">
          <Header className="app-header">
            <div className="workspace-breadcrumb">
              {!screens.lg && <>
                <Button type="text" aria-label="打开导航" icon={<MenuUnfoldOutlined />} onClick={() => setDrawerOpen(true)} />
                <Button type="text" aria-label="打开快捷导航命令面板" icon={<SearchOutlined />} onClick={openCommands} />
              </>}
              <span className="workspace-crumb-brand">CivicEcho</span>
              <span className="workspace-crumb-space">{workspace}</span>
              {active && <span className="workspace-crumb-page" aria-current="page">{active.label}</span>}
            </div>
            <div className="workspace-header-actions">
            <WorkspaceNotifications key={user.id} user={user} />
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  { key: 'change-password', icon: <LockOutlined />, label: '修改密码', onClick: openChangePassword },
                  { key: 'switch', icon: <SwapOutlined />, label: '切换账号', onClick: leave },
                  { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: leave },
                ],
              }}
            >
              <Button
                type="text"
                className="account-menu-trigger"
                aria-label={`${user.display_name}，${roleLabels[user.role]}，账号菜单`}
              >
                <Avatar size={26} className="workspace-avatar">{user.display_name.slice(0, 1)}</Avatar>
                <span className="workspace-account">
                  <strong>{user.display_name}</strong>
                  <small>{roleLabels[user.role]}</small>
                </span>
                <DownOutlined className="workspace-account-caret" />
              </Button>
            </Dropdown>
            </div>
          </Header>
          <Content key={user.id} id="main-content" tabIndex={-1} className="app-content">
            <Outlet />
          </Content>
        </Layout>
      </div>

      <Modal
        title="快捷跳转"
        open={cmdOpen}
        onCancel={() => setCmdOpen(false)}
        afterClose={() => cmdInvoker.current?.focus()}
        focusable={{ focusTriggerAfterClose: false }}
        footer={null}
        width={480}
        className="ce-cmd-modal"
        styles={{ body: { padding: 0 } }}
        destroyOnHidden
      >
        <div className="ce-cmd-head">
          <SearchOutlined aria-hidden className="ce-cmd-icon" />
          <Input
            variant="borderless"
            autoFocus
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={cmdOpen}
            aria-controls="workspace-command-list"
            aria-activedescendant={cmdIndex >= 0 ? `workspace-command-${cmdIndex}` : undefined}
            value={cmdQuery}
            onChange={(e) => { setCmdQuery(e.target.value); setCmdIndex(-1) }}
            placeholder={`在「${workspace}」中快速跳转页面…`}
            aria-label="搜索快捷页面"
            onKeyDown={handleCommandKeys}
          />
          <kbd className="ce-kbd">ESC</kbd>
        </div>
        <div ref={commandList} id="workspace-command-list" className="ce-cmd-list" role="listbox" aria-label="可跳转页面">
            {filteredCmd.map((item, index) => (
              <button
                key={item.key}
                id={`workspace-command-${index}`}
                type="button"
                role="option"
                aria-selected={cmdIndex === index}
                tabIndex={-1}
                className="ce-cmd-item"
                onClick={() => goToCommand(item.key)}
              >
                <span className="ce-cmd-item-label">{item.icon}<span>{item.label}</span></span>
                <span className="ce-cmd-item-path">{item.key}</span>
              </button>
            ))}
        </div>
        {filteredCmd.length === 0 && <div className="ce-cmd-empty" role="status">未找到匹配页面</div>}
        <div className="ce-cmd-actions">
          <div className="ce-cmd-divider" />
          <button
            type="button"
            className="ce-cmd-item"
            onClick={() => { setCmdOpen(false); leave() }}
          >
            <span className="ce-cmd-item-label"><SwapOutlined /><span>切换登录账号</span></span>
            <span className="ce-cmd-item-path">/login</span>
          </button>
        </div>
      </Modal>
      <Modal
        title="修改密码"
        open={pwOpen}
        onCancel={closeChangePassword}
        onOk={() => pwForm.submit()}
        confirmLoading={pwBusy}
        okText="确认修改"
        cancelText="取消"
        width={440}
        destroyOnHidden
      >
        <Form form={pwForm} layout="vertical" onFinish={submitChangePassword} requiredMark={false}>
          {pwError && <Alert type="error" showIcon role="alert" title={pwError} style={{ marginBottom: 16 }} />}
          <Form.Item
            label="当前密码"
            name="current_password"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password autoComplete="current-password" placeholder="请输入当前登录密码" />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="new_password"
            dependencies={['current_password']}
            extra="至少 8 位，且须同时包含字母和数字"
            rules={[
              { required: true, message: '请输入新密码' },
              {
                validator: (_, value?: string) => {
                  if (!value) return Promise.resolve()
                  if (value.length < 8 || !/[A-Za-z]/.test(value) || !/\d/.test(value)) {
                    return Promise.reject(new Error('新密码须至少 8 位，且同时包含字母和数字'))
                  }
                  if (value === pwForm.getFieldValue('current_password')) {
                    return Promise.reject(new Error('新密码不能与当前密码相同'))
                  }
                  return Promise.resolve()
                },
              },
            ]}
          >
            <Input.Password autoComplete="new-password" placeholder="请输入新密码" />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirm_password"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              {
                validator: (_, value?: string) => {
                  if (!value || pwForm.getFieldValue('new_password') === value) {
                    return Promise.resolve()
                  }
                  return Promise.reject(new Error('两次输入的新密码不一致'))
                },
              },
            ]}
          >
            <Input.Password autoComplete="new-password" placeholder="请再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}
