import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'
import { AftercarePage } from './AftercarePage'

vi.mock('../auth/AuthContext',()=>({useAuth:()=>({user:{id:4,role:'admin',display_name:'管理员'}})}))
vi.mock('../api/aftercare',async()=>{const actual=await vi.importActual<typeof import('../api/aftercare')>('../api/aftercare');return {...actual,
  listFollowUps:vi.fn().mockResolvedValue({items:[{id:'f1',ticket_id:'QT2026071400000001',handling_round:1,status:'pending',due_at:'2026-07-16T10:00:00Z',created_at:'2026-07-14T10:00:00Z',updated_at:'2026-07-14T10:00:00Z',records:[]}],page:1,page_size:100,total:1}),
  listAppeals:vi.fn().mockResolvedValue({items:[{id:'a1',appeal_no:'QT2026071400000001-SS-1',ticket_id:'QT2026071400000001',sequence:1,status:'submitted',reason:'首次处理没有覆盖夜间反复出现的问题',desired_resolution:'安排夜间复查',created_at:'2026-07-14T10:00:00Z',updated_at:'2026-07-14T10:00:00Z'}],page:1,page_size:100,total:1}),
  reviewAppeal:vi.fn(),recordPhoneFollowUp:vi.fn(),createAppeal:vi.fn(),
}})

describe('AftercarePage',()=>{
  it('shows automatic follow-up and opens appeal review for administrators',async()=>{
    renderApp(<MemoryRouter><AftercarePage/></MemoryRouter>)
    expect(await screen.findByText('待回访')).toBeInTheDocument()
    expect(screen.getByText('QT2026071400000001-SS-1')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button',{name:'审核申诉'}))
    expect(await screen.findByRole('dialog',{name:'申诉审核'})).toBeInTheDocument()
    expect(screen.getByLabelText('重新办理要求')).toBeInTheDocument()
    await act(async()=>{await new Promise(r=>setTimeout(r,0))})
  })
})
