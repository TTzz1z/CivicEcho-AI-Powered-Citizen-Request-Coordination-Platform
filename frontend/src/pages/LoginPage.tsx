import { Alert, Button, Divider, Form, Input, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { login } from '../api/auth'
import { ApiError } from '../api/client'
import { getOidcConfig, type OidcConfig } from '../api/intelligence'
import { useAuth } from '../auth/AuthContext'
import { loginTargetForRole } from '../routes/guards'

export function LoginPage(){
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [oidc,setOidc]=useState<OidcConfig|null>(null)
  const {refresh}=useAuth();const nav=useNavigate();const location=useLocation()
  useEffect(()=>{void getOidcConfig().then(setOidc).catch(()=>undefined)},[])
  const submit=async(v:{username:string;password:string})=>{setBusy(true);setError('');try{await login(v.username,v.password);const user=await refresh();const requestedPath=(location.state as {from?:{pathname?:string}})?.from?.pathname;nav(user?loginTargetForRole(user.role,requestedPath):'/',{replace:true,state:null})}catch(e){setError(e instanceof ApiError?e.message:'登录失败，请重试')}finally{setBusy(false)}}
  const startOidc=()=>{if(!oidc?.authorization_endpoint||!oidc.client_id||!oidc.redirect_uri)return;const state=crypto.randomUUID();sessionStorage.setItem('tingting_oidc_state',state);const query=new URLSearchParams({client_id:oidc.client_id,redirect_uri:oidc.redirect_uri,response_type:'code',scope:oidc.scopes,state});window.location.assign(`${oidc.authorization_endpoint}?${query}`)}
  return <main className="login-shell"><section className="login-story"><div className="page-eyebrow" style={{color:'#7ed8cb'}}>TINGTING ASSISTANT</div><h1>一套工作台，<br/>连接市民与办理部门。</h1><p>身份与数据权限由后端统一校验；工单每次流转携带版本号，保证多人协同时数据可靠、操作可追溯。</p></section><section className="login-form-wrap"><div className="login-card"><Typography.Title level={2}>登录倾听助手</Typography.Title><p className="page-description" style={{marginBottom:28}}>市民、坐席、部门人员和管理员使用已分配账号进入各自服务界面</p>{error&&<Alert role="alert" showIcon type="error" message={error} style={{marginBottom:20}}/>}<Form layout="vertical" size="large" onFinish={submit}><Form.Item label="用户名" name="username" rules={[{required:true,message:'请输入用户名'}]}><Input prefix={<UserOutlined/>} autoComplete="username" placeholder="请输入用户名"/></Form.Item><Form.Item label="密码" name="password" rules={[{required:true,message:'请输入密码'}]}><Input.Password prefix={<LockOutlined/>} autoComplete="current-password" placeholder="请输入密码"/></Form.Item><Button type="primary" htmlType="submit" loading={busy} block>安全登录</Button></Form>{oidc?.enabled&&<><Divider plain>或</Divider><Button block onClick={startOidc}>统一身份认证登录</Button></>}<div style={{textAlign:'center',marginTop:20}}><Link to="/welcome">返回服务首页</Link></div></div></section></main>
}
