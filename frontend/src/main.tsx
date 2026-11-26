import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import { ServiceStatus } from './components/ServiceStatus'
import { AppRoutes } from './routes/AppRoutes'
import { civicTheme } from './styles/theme'
import './styles/tokens.css'
import './styles/global.css'
import './styles/workspace.css'

export const queryClient=new QueryClient({defaultOptions:{queries:{retry:(count,error)=>!(error instanceof Error&&'status'in error&&[401,403,404].includes((error as {status:number}).status))&&count<2,staleTime:20_000},mutations:{retry:false}}})
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <ConfigProvider locale={zhCN} theme={civicTheme}>
        <AntApp message={{ maxCount: 1 }}>
          <QueryClientProvider client={queryClient}>
            <BrowserRouter>
              <ServiceStatus />
              <AuthProvider>
                <AppRoutes />
              </AuthProvider>
            </BrowserRouter>
          </QueryClientProvider>
        </AntApp>
      </ConfigProvider>
    </AppErrorBoundary>
  </React.StrictMode>
)
