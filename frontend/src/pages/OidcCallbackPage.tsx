import { useEffect, useState } from 'react'
import { Alert, Card, Spin } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { exchangeOidcCode, getOidcConfig } from '../api/intelligence'
import { tokenStore } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { loginTargetForRole } from '../routes/guards'

export function OidcCallbackPage(){const [params]=useSearchParams();const [error,setError]=useState('');const {refresh}=useAuth();const nav=useNavigate();useEffect(()=>{void(async()=>{try{const code=params.get('code');const state=params.get('state');const expected=sessionStorage.getItem('tingting_oidc_state');sessionStorage.removeItem('tingting_oidc_state');if(!state||!expected||state!==expected)throw new Error('统一身份认证状态校验失败，请重新登录');if(!code)throw new Error('统一身份认证未返回授权码');const config=await getOidcConfig();if(!config.redirect_uri)throw new Error('OIDC 回调地址未配置');const result=await exchangeOidcCode(code,config.redirect_uri);tokenStore.set(result.access_token);const user=await refresh();nav(user?loginTargetForRole(user.role):'/',{replace:true})}catch(e){setError(e instanceof Error?e.message:'统一身份认证失败')}})()},[nav,params,refresh]);return <main className="login-shell"><Card className="login-card">{error?<Alert type="error" showIcon message={error}/>:<Spin tip="正在完成统一身份认证"/>}</Card></main>}
