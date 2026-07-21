import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/client'
import { allowedActions } from './TicketDetailPage'

describe('ticket permissions and conflict',()=>{
  it('only exposes state-valid actions',()=>{
    expect(allowedActions('agent','pending')).toEqual(['accept','reject','contact','remind'])
    expect(allowedActions('department_staff','assigned')).toEqual(['process','pause_sla','remind'])
    expect(allowedActions('department_staff','processing')).toEqual(['note','pause_sla','remind'])
    expect(allowedActions('citizen','processing')).toEqual(['remind'])
    expect(allowedActions('citizen','resolved')).toEqual(['feedback'])
    expect(allowedActions('admin','resolved')).toEqual(['close','process'])
  })
  it('preserves 409 conflict semantics',()=>{const error=new ApiError(409,'VERSION_CONFLICT','工单数据已被其他操作更新');expect(error.status).toBe(409);expect(error.message).toContain('更新')})
})
