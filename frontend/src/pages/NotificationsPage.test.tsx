import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'
import { readAllNotifications } from '../api/aftercare'
import { NotificationsPage } from './NotificationsPage'

vi.mock('../auth/AuthContext',()=>({useAuth:()=>({user:{id:1,role:'citizen',display_name:'市民'}})}))
vi.mock('../api/aftercare',async()=>{const actual=await vi.importActual<typeof import('../api/aftercare')>('../api/aftercare');return {...actual,
  listNotifications:vi.fn().mockResolvedValue({items:[{id:'n1',ticket_id:'QT2026071400000001',event_type:'awaiting_confirmation',channel:'in_app',title:'等待市民确认',content:'请查看办理结果并确认',status:'unread',delivery_status:'delivered',created_at:'2026-07-14T10:00:00Z'}],page:1,page_size:20,total:1,unread_count:1}),
  listNotificationChannels:vi.fn().mockResolvedValue([{channel:'in_app',label:'站内通知',enabled:true,phase:'P1'},{channel:'sms',label:'短信',enabled:false,phase:'reserved'}]),
  readNotification:vi.fn().mockResolvedValue({}),readAllNotifications:vi.fn().mockResolvedValue({read_count:1}),
}})

describe('NotificationsPage',()=>{
  it('shows unread workflow events and reserved channels',async()=>{
    renderApp(<MemoryRouter><NotificationsPage/></MemoryRouter>)
    expect(await screen.findByText('等待市民确认')).toBeInTheDocument()
    expect(screen.getByText('站内通知 · 已启用')).toBeInTheDocument()
    expect(screen.getByText('短信 · 已预留')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button',{name:/全部已读/}))
    await waitFor(()=>expect(readAllNotifications).toHaveBeenCalled())
  })
})
