import { screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'
import { listTickets } from '../api/tickets'
import { TicketsPage } from './TicketsPage'
vi.mock('../auth/AuthContext',()=>({useAuth:()=>({user:{id:2,role:'agent',display_name:'坐席'}})}))
vi.mock('../api/tickets',async()=>{const actual=await vi.importActual<typeof import('../api/tickets')>('../api/tickets');return {...actual,listTickets:vi.fn().mockResolvedValue({items:[],page:1,page_size:20,total:0})}})
describe('TicketsPage',()=>{it('restores filters from the URL and sends them to backend',async()=>{renderApp(<MemoryRouter initialEntries={['/agent/tickets?status=pending&keyword=%E8%B7%AF%E7%81%AF']}><TicketsPage/></MemoryRouter>);await waitFor(()=>expect(listTickets).toHaveBeenCalledWith(expect.objectContaining({status:'pending',keyword:'路灯'})));expect(screen.getByText('当前条件下暂无工单')).toBeInTheDocument()})})
