import { Button, Result } from 'antd'
import { Link } from 'react-router-dom'
export function ForbiddenPage(){return <Result status="403" title="无权访问" subTitle="当前账号没有访问此页面的权限。后端仍会对每次请求执行最终权限校验。" extra={<Link to="/"><Button type="primary">返回我的工作台</Button></Link>}/>}export function NotFoundPage(){return <Result status="404" title="页面不存在" subTitle="你访问的地址无效，或资源已不存在。" extra={<Link to="/"><Button type="primary">返回首页</Button></Link>}/>} 
