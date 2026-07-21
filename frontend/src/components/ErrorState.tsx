import { Button, Result } from 'antd'
import { ApiError } from '../api/client'
export function ErrorState({error,retry}:{error:unknown;retry?:()=>void}){const apiError=error instanceof ApiError?error:null;const status=apiError?.status===403?'403':apiError?.status===404?'404':'500';return <Result status={status} title={apiError?.message||'页面暂时无法加载'} subTitle={apiError?.status===409?'数据已被他人更新，请重新加载后继续。':'请稍后重试；若问题持续，请联系系统管理员。'} extra={retry&&<Button type="primary" onClick={retry}>重新加载</Button>}/>} 
