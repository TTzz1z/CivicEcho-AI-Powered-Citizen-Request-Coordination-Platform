import { useState } from 'react'
import { Alert, Button, Card, Col, Descriptions, Empty, Form, Input, List, Progress, Row, Space, Tag, Typography, message } from 'antd'
import { BulbOutlined, CloudSyncOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { analyzeTicket, listHotspots, listIntegrationStatuses, listSuggestions, reviewSuggestion, syncDirectory, syncExternalTicket } from '../api/intelligence'
import type { AiSuggestion, AiSuggestionType } from '../types'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { CitizenPreReview } from './CitizenPreReview'

const typeLabels:Record<AiSuggestionType,string>={assignment:'责任部门建议',similarity:'相似与重复检测',summary:'诉求摘要',completeness:'信息完整性',document_draft:'处理文书草稿',risk:'敏感紧急提示'}
const integrationLabels:Record<string,string>={oidc:'统一身份认证',directory:'组织人员目录',work_order:'政务工单平台',sms:'短信服务',map:'地图服务',division:'行政区划',logging:'集中日志',monitoring:'监控平台'}

function ResultBody({item}:{item:AiSuggestion}){
  const value=item.result
  if(item.suggestion_type==='summary')return <><Typography.Paragraph copyable>{String(value.summary||'')}</Typography.Paragraph><Descriptions size="small" column={1} items={[{key:'impact',label:'影响范围',children:String(value.impact||'待评估')},{key:'urgency',label:'紧迫程度',children:<Tag color={String(value.urgency_hint||'').includes('基本生活')?'red':String(value.urgency_hint||'').includes('安全')?'orange':'default'}>{String(value.urgency_hint||'一般性诉求')}</Tag>}]}/></>
  if(item.suggestion_type==='completeness')return <Descriptions size="small" column={1} items={[{key:'state',label:'结论',children:value.complete?'信息完整':'建议补充信息'},{key:'missing',label:'缺失项',children:(value.missing_fields as string[]||[]).join('、')||'无'},{key:'warnings',label:'提醒',children:(value.warnings as string[]||[]).join('；')||'无'},{key:'tips',label:'补充建议',children:(value.tips as string[]||[]).join('；')||'无'}]}/>
  if(item.suggestion_type==='risk')return <><Alert showIcon type={value.level==='urgent'?'error':value.level==='sensitive'?'warning':'success'} message={String(value.recommendation||'')} description={`命中信号：${(value.matched_signals as string[]||[]).join('、')||'无'}`}/>{value.time_limit_hint&&<div style={{marginTop:8}}><Tag color="blue">建议时限：{String(value.time_limit_hint)}</Tag>{(value.suggested_departments as string[]||[]).length>0&&<Tag color="cyan">建议联系：{(value.suggested_departments as string[]).join('、')}</Tag>}</div>}</>
  if(item.suggestion_type==='assignment')return <><List size="small" dataSource={(value.recommended_departments as {department_name:string;score?:number;historical_cases?:number;reason?:string;confidence?:string}[]||[])} locale={{emptyText:'暂无足够历史数据'}} renderItem={row=><List.Item><Space wrap><b>{row.department_name}</b>{row.score!=null&&<Tag>{Math.round(row.score*100)}%</Tag>}{row.confidence&&<Tag color={row.confidence==='high'?'green':row.confidence==='medium'?'orange':'default'}>{row.confidence==='high'?'高置信':row.confidence==='medium'?'中置信':'低置信'}</Tag>}{row.reason&&<Typography.Text type="secondary">{row.reason}</Typography.Text>}{row.historical_cases!=null&&<Typography.Text type="secondary">参考历史 {row.historical_cases} 件</Typography.Text>}</Space></List.Item>}/>{value.dispatch_hint&&<Alert type="info" showIcon message={String(value.dispatch_hint)} style={{marginTop:8}}/>}</>
  if(item.suggestion_type==='similarity')return <List size="small" dataSource={(value.matches as {ticket_id:string;score:number;duplicate_likelihood:string;status?:string}[]||[])} locale={{emptyText:'未发现明显相似诉求'}} renderItem={row=><List.Item><Space wrap><b>{row.ticket_id}</b><Tag color={row.duplicate_likelihood==='high'?'red':'orange'}>{Math.round(row.score*100)}% 相似</Tag>{row.duplicate_likelihood==='high'&&<Tag color="red">建议合并</Tag>}{row.status&&<Tag>{row.status}</Tag>}</Space></List.Item>}/>
  if(item.suggestion_type==='document_draft')return <><Alert type="warning" showIcon message={String(value.prohibited_use||'草稿必须人工复核')} style={{marginBottom:12}}/><Typography.Paragraph copyable style={{whiteSpace:'pre-wrap'}}>{String(value.body||'')}</Typography.Paragraph></>
  return <pre className="ai-json-result">{JSON.stringify(value,null,2)}</pre>
}

export function IntelligencePage(){
  const {user}=useAuth()
  // 市民端使用全新的“提交前智能预审”页面
  if(user?.role==='citizen') return <CitizenPreReview/>
  return <StaffAiWorkbench/>
}

function StaffAiWorkbench(){
  const {user}=useAuth();const qc=useQueryClient();const [form]=Form.useForm<{ticket_id:string}>();const [suggestions,setSuggestions]=useState<AiSuggestion[]>([])
  const staff=true;const admin=user?.role==='admin'
  const types:AiSuggestionType[]=staff?['assignment','similarity','summary','completeness','document_draft','risk']:['similarity','summary','completeness','risk']
  const canSync=user?.role==='agent'||user?.role==='admin'
  const mergeSuggestions=(incoming:AiSuggestion[])=>setSuggestions(prev=>{const byType=new Map<string,AiSuggestion>();for(const item of [...prev,...incoming]){const existing=byType.get(item.suggestion_type);if(!existing||item.created_at>existing.created_at)byType.set(item.suggestion_type,item)}return Array.from(byType.values()).sort((a,b)=>b.created_at.localeCompare(a.created_at))})
  const analyze=useMutation({mutationFn:(ticketId:string)=>analyzeTicket(ticketId.trim().toUpperCase(),types),onSuccess:data=>{mergeSuggestions(data);message.success('AI 建议已生成，仅供人工参考')},onError:e=>message.error(e instanceof ApiError?e.message:'分析失败')})
  const history=useMutation({mutationFn:(ticketId:string)=>listSuggestions(ticketId.trim().toUpperCase()),onSuccess:data=>{if(data.length===0){message.info('该工单暂无历史建议')}else{mergeSuggestions(data);message.success(`已加载 ${data.length} 条历史建议`)}},onError:e=>message.error(e instanceof ApiError?e.message:'加载历史建议失败')})
  const hotspots=useQuery({queryKey:['ai','hotspots'],queryFn:()=>listHotspots(30),enabled:staff})
  const integrations=useQuery({queryKey:['integrations','status'],queryFn:listIntegrationStatuses,enabled:admin})
  const directory=useMutation({mutationFn:syncDirectory,onSuccess:r=>{message.success(`目录同步完成：新增 ${r.created}，更新 ${r.updated}`);void qc.invalidateQueries({queryKey:['integrations']})},onError:e=>message.error(e instanceof Error?e.message:'同步失败')})
  const external=useMutation({mutationFn:(id:string)=>syncExternalTicket(id),onSuccess:r=>message.success(`已同步外部工单 ${r.external_ticket_id}`),onError:e=>message.error(e instanceof Error?e.message:'同步失败')})
  const review=async(item:AiSuggestion,decision:'helpful'|'not_helpful')=>{await reviewSuggestion(item.id,decision);setSuggestions(current=>current.map(row=>row.id===item.id?{...row,review_decision:decision}:row));message.success('评价已记录')}
  return <>
    <PageHeader eyebrow="AI ADVISORY" title={user?.role==='citizen'?'智能诉求检查':'智能辅助工作台'} description="AI 只提供摘要、线索和草稿；受理、拒绝、派发、办结等行政决定必须由有权限的工作人员完成。"/>
    <Alert className="surface" showIcon icon={<SafetyCertificateOutlined/>} type="warning" message="人机协同边界" description="系统不会把任何 AI 输出自动写入工单状态或行政决定。敏感、紧急提示必须由人工核实，文书草稿必须逐项核对事实。" style={{marginBottom:20}}/>
    <Card className="surface" title="按工单生成建议" extra={<BulbOutlined/>}>
      <Form form={form} layout="inline" onFinish={v=>{setSuggestions([]);analyze.mutate(v.ticket_id)}}><Form.Item name="ticket_id" label="工单编号" rules={[{required:true,message:'请输入工单编号'}]}><Input aria-label="工单编号" placeholder="QT2026071400000001" style={{width:240}}/></Form.Item><Form.Item><Space><Button type="primary" htmlType="submit" loading={analyze.isPending}>生成 AI 建议</Button><Button loading={history.isPending} onClick={()=>{const id=form.getFieldValue('ticket_id');if(id){setSuggestions([]);history.mutate(id)}else message.warning('请先输入工单编号')}}>加载历史建议</Button>{canSync&&<Button icon={<CloudSyncOutlined/>} loading={external.isPending} onClick={()=>{const id=form.getFieldValue('ticket_id');if(id)external.mutate(id);else message.warning('请先输入工单编号')}}>同步真实工单平台</Button>}</Space></Form.Item></Form>
    </Card>
    <Row gutter={[20,20]} style={{marginTop:20}}>{suggestions.map(item=><Col xs={24} lg={12} key={item.id}><Card className="surface ai-suggestion-card" title={<Space>{typeLabels[item.suggestion_type]}{item.risk_level!=='none'&&<Tag color={item.risk_level==='urgent'?'red':'orange'}>{item.risk_level}</Tag>}</Space>} extra={<Progress type="circle" percent={item.confidence} size={42}/>}><ResultBody item={item}/><Typography.Text type="secondary">{item.explanation}</Typography.Text><div style={{marginTop:14}}><Space><Button size="small" type={item.review_decision==='helpful'?'primary':'default'} onClick={()=>void review(item,'helpful')}>有帮助</Button><Button size="small" danger={item.review_decision==='not_helpful'} onClick={()=>void review(item,'not_helpful')}>无帮助</Button></Space></div></Card></Col>)}</Row>
    {staff&&<Card className="surface" title="近 30 天热点问题聚类" style={{marginTop:20}}>{hotspots.isError?<ErrorState error={hotspots.error} retry={()=>hotspots.refetch()}/>:<List loading={hotspots.isLoading} dataSource={hotspots.data} locale={{emptyText:<Empty description="当前可见范围内尚未形成热点聚类"/>}} renderItem={item=><List.Item><List.Item.Meta title={<Space>{item.label}<Tag color="blue">{item.count} 件</Tag>{item.urgent_count>0&&<Tag color="red">紧急 {item.urgent_count}</Tag>}</Space>} description={`样本工单：${item.sample_ticket_ids.join('、')}`}/></List.Item>}/>}</Card>}
    {admin&&<Card className="surface" title="真实平台接入状态" style={{marginTop:20}} extra={<Button loading={directory.isPending} onClick={()=>directory.mutate()}>同步组织人员目录</Button>}>{integrations.isError?<ErrorState error={integrations.error} retry={()=>integrations.refetch()}/>:<List loading={integrations.isLoading} grid={{gutter:12,xs:1,sm:2,lg:4}} dataSource={integrations.data} renderItem={item=><List.Item><Card size="small"><b>{integrationLabels[item.integration_type]||item.integration_type}</b><div style={{margin:'10px 0'}}><Tag color={item.configured?'green':'default'}>{item.configured?'已配置':'待配置'}</Tag><Tag>{item.mode}</Tag></div><Typography.Text type="secondary">{item.message}</Typography.Text></Card></List.Item>}/>}</Card>}
  </>
}
