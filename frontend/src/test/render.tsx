import { ConfigProvider } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderOptions } from '@testing-library/react'
import type { ReactElement } from 'react'
export function renderApp(ui:ReactElement,options?:RenderOptions){const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});return render(<ConfigProvider theme={{token:{motion:false}}}><QueryClientProvider client={client}>{ui}</QueryClientProvider></ConfigProvider>,options)}
