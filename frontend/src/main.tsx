import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { ServiceStatus } from './components/ServiceStatus'
import { AppRoutes } from './routes/AppRoutes'
import './styles/global.css'

export const queryClient=new QueryClient({defaultOptions:{queries:{retry:(count,error)=>!(error instanceof Error&&'status'in error&&[401,403,404].includes((error as {status:number}).status))&&count<2,staleTime:20_000},mutations:{retry:false}}})
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><ConfigProvider locale={zhCN} theme={{token:{colorPrimary:'#167c72',colorInfo:'#167c72',colorText:'#142b3b',colorBgLayout:'#f3f6f6',borderRadius:8,fontFamily:'"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif'},components:{Layout:{siderBg:'#12344d',headerBg:'#ffffff'},Menu:{darkItemBg:'#12344d',darkItemSelectedBg:'#1a756f'}}}}><AntApp><QueryClientProvider client={queryClient}><BrowserRouter><ServiceStatus/><AuthProvider><AppRoutes/></AuthProvider></BrowserRouter></QueryClientProvider></AntApp></ConfigProvider></React.StrictMode>
)
