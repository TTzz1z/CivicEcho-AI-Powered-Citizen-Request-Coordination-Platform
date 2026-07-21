import { Tag } from 'antd'
import type { TicketStatus } from '../types'
const meta:Record<TicketStatus,{label:string;color:string}>={pending:{label:'待受理',color:'gold'},accepted:{label:'已受理',color:'cyan'},assigned:{label:'已派发',color:'blue'},processing:{label:'处理中',color:'processing'},resolved:{label:'待市民确认',color:'purple'},closed:{label:'已办结',color:'success'},rejected:{label:'不予受理',color:'default'}}
export function TicketStatusTag({status,label}:{status:TicketStatus;label?:string}){const item=meta[status];return <Tag color={item.color}>{label||item.label}</Tag>}
export const statusOptions=Object.entries(meta).map(([value,item])=>({value,label:item.label}))
