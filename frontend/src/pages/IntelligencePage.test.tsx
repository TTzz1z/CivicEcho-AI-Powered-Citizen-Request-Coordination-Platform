import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'
import { IntelligencePage } from './IntelligencePage'

vi.mock('antd',async()=>{const actual=await vi.importActual<typeof import('antd')>('antd');return {...actual,message:{success:vi.fn(),error:vi.fn(),warning:vi.fn()}}})
vi.mock('../auth/AuthContext',()=>({useAuth:()=>({user:{id:2,role:'agent',display_name:'坐席'}})}))
vi.mock('../api/intelligence',()=>({
  analyzeTicket:vi.fn().mockResolvedValue([{id:'a1',ticket_id:'QT2026071400000001',suggestion_type:'risk',status:'completed',risk_level:'urgent',confidence:95,provider:'rules',model_name:'phase6-rules-v1',result:{level:'urgent',matched_signals:['燃气泄漏'],recommendation:'请立即由人工核实并按应急预案升级'},explanation:'仅供人工参考',created_at:'2026-07-14T10:00:00Z',advisory_only:true}]),
  listHotspots:vi.fn().mockResolvedValue([{cluster_key:'1:幸福',label:'燃气安全 · 幸福路社区',count:4,urgent_count:1,sample_ticket_ids:['QT1','QT2']}]),
  listIntegrationStatuses:vi.fn().mockResolvedValue([]),reviewSuggestion:vi.fn().mockResolvedValue({}),syncDirectory:vi.fn(),syncExternalTicket:vi.fn(),
}))

describe('IntelligencePage',()=>{
  it('states the human decision boundary and renders urgent advisory results',async()=>{
    renderApp(<MemoryRouter><IntelligencePage/></MemoryRouter>)
    expect(screen.getByText('人机协同边界')).toBeInTheDocument()
    expect(await screen.findByText('燃气安全 · 幸福路社区')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('工单编号'),'QT2026071400000001')
    await userEvent.click(screen.getByRole('button',{name:'生成 AI 建议'}))
    expect(await screen.findByText('敏感紧急提示')).toBeInTheDocument()
    expect(screen.getByText('请立即由人工核实并按应急预案升级')).toBeInTheDocument()
    expect(screen.getByRole('button',{name:'有帮助'})).toBeInTheDocument()
  })
})
