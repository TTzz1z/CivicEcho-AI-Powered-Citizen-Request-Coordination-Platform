import { Button, Result } from 'antd'
import { useAuth } from '../auth/AuthContext'

export function ForbiddenPage() {
  const { user } = useAuth()
  return <main><Result
    status="403"
    title="无权访问"
    subTitle="当前账号没有访问此页面的权限。"
    extra={<Button href={user ? '/' : '/login'} type="primary">{user ? '返回我的工作台' : '前往登录'}</Button>}
  /></main>
}

export function NotFoundPage() {
  return <main><Result
    status="404"
    title="页面不存在"
    subTitle="该地址无效，或页面已移动。"
    extra={<Button href="/welcome" type="primary">返回服务首页</Button>}
  /></main>
}
