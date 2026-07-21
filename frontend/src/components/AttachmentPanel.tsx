import { DeleteOutlined, DownloadOutlined, EyeInvisibleOutlined, FileProtectOutlined, InboxOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Empty, Form, Input, List, Modal, Select, Space, Tag, Upload, message, type UploadFile } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'
import { attachmentKeys, deleteAttachment, downloadAttachment, listAttachments, uploadAttachment } from '../api/attachments'
import { ApiError } from '../api/client'
import type { AttachmentType, AttachmentVisibility, TicketAttachment, TicketStatus, User } from '../types'

const typeLabels:Record<AttachmentType,string>={citizen_material:'市民补充材料',site_photo:'现场照片',official_document:'办理文书',processing_proof:'处理证明',other:'其他材料'}
const accept='.jpg,.jpeg,.png,.webp,.pdf,.doc,.docx,.xls,.xlsx,.txt'

function formatBytes(bytes:number){if(bytes<1024)return `${bytes} B`;if(bytes<1024*1024)return `${(bytes/1024).toFixed(1)} KB`;return `${(bytes/1024/1024).toFixed(1)} MB`}
function typeOptions(user:User|null){
  if(user?.role==='citizen')return ['citizen_material','other'] as AttachmentType[]
  if(user?.role==='department_staff')return ['site_photo','official_document','processing_proof','other'] as AttachmentType[]
  return ['citizen_material','site_photo','official_document','processing_proof','other'] as AttachmentType[]
}

export function AttachmentPanel({ticketId,status,user}:{ticketId:string;status:TicketStatus;user:User|null}){
  const qc=useQueryClient();const [uploadOpen,setUploadOpen]=useState(false);const [deleteTarget,setDeleteTarget]=useState<TicketAttachment|null>(null)
  const [fileList,setFileList]=useState<UploadFile[]>([]);const [uploadForm]=Form.useForm<{attachment_type:AttachmentType;visibility:AttachmentVisibility}>();const [deleteForm]=Form.useForm<{reason:string}>()
  const query=useQuery({queryKey:attachmentKeys.ticket(ticketId),queryFn:()=>listAttachments(ticketId)})
  const uploadMutation=useMutation({mutationFn:async(v:{attachment_type:AttachmentType;visibility:AttachmentVisibility})=>{
    const file=fileList[0]?.originFileObj;if(!file)throw new Error('请选择要上传的文件')
    return uploadAttachment(ticketId,file,v.attachment_type,user?.role==='citizen'?'public':v.visibility)
  },onSuccess:()=>{message.success('附件已完成校验并上传');setUploadOpen(false);setFileList([]);uploadForm.resetFields();void qc.invalidateQueries({queryKey:attachmentKeys.ticket(ticketId)})},onError:e=>message.error(e instanceof Error?e.message:'附件上传失败')})
  const deleteMutation=useMutation({mutationFn:(v:{reason:string})=>deleteAttachment(deleteTarget!.id,v.reason),onSuccess:()=>{message.success('附件已删除并记录审计');setDeleteTarget(null);deleteForm.resetFields();void qc.invalidateQueries({queryKey:attachmentKeys.ticket(ticketId)})},onError:e=>message.error(e instanceof Error?e.message:'附件删除失败')})
  const canUpload=!!user&&!(user.role==='citizen'&&['closed','rejected'].includes(status))
  const openUpload=()=>{setFileList([]);uploadForm.setFieldsValue({attachment_type:user?.role==='citizen'?'citizen_material':'site_photo',visibility:'public'});setUploadOpen(true)}
  const startDownload=async(item:TicketAttachment)=>{try{await downloadAttachment(item)}catch(e){message.error(e instanceof ApiError?e.message:'附件下载失败')}}
  return <>
    <Card className="surface detail-card attachment-panel" style={{marginTop:20}} title={<Space><FileProtectOutlined/>附件与办理证据</Space>} extra={canUpload?<Button type="primary" onClick={openUpload}>上传附件</Button>:null}>
      <Alert className="attachment-guidance" type="info" showIcon message={user?.role==='citizen'?'公开附件将随工单提供给办理人员；请勿上传无关隐私信息。':'标记为“内部”的附件不会向市民展示。文件通过安全校验后才会保存。'}/>
      {query.isError?<Alert type="error" showIcon message={query.error instanceof Error?query.error.message:'附件加载失败'} action={<Button size="small" onClick={()=>query.refetch()}>重试</Button>}/>:query.isLoading?<Card loading bordered={false}/>:query.data?.items.length?<List className="attachment-list" dataSource={query.data.items} renderItem={item=><List.Item actions={[
        <Button key="download" type="text" icon={<DownloadOutlined/>} aria-label={`下载 ${item.original_filename}`} onClick={()=>void startDownload(item)}>下载</Button>,
        (user?.role==='admin'||user?.role==='department_staff'||item.uploader_user_id===user?.id)?<Button key="delete" type="text" danger icon={<DeleteOutlined/>} aria-label={`删除 ${item.original_filename}`} onClick={()=>{deleteForm.resetFields();setDeleteTarget(item)}}>删除</Button>:null,
      ].filter(Boolean)}><List.Item.Meta avatar={<div className="attachment-icon"><FileProtectOutlined/></div>} title={<Space wrap><span>{item.original_filename}</span><Tag>{typeLabels[item.attachment_type]}</Tag>{item.visibility==='internal'&&<Tag icon={<EyeInvisibleOutlined/>} color="gold">内部</Tag>}<Tag icon={<SafetyCertificateOutlined/>} color={item.scan_status==='clean'?'green':'default'}>{item.scan_status==='clean'?'扫描通过':'开发环境未扫描'}</Tag></Space>} description={`${formatBytes(item.size_bytes)} · ${dayjs(item.created_at).format('YYYY-MM-DD HH:mm')} · SHA-256 ${item.sha256.slice(0,12)}…`}/></List.Item>}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无附件或办理证据"/>}
    </Card>
    <Modal title="上传附件与办理证据" open={uploadOpen} onCancel={()=>setUploadOpen(false)} onOk={()=>uploadForm.submit()} okText="校验并上传" confirmLoading={uploadMutation.isPending} destroyOnHidden>
      <Form form={uploadForm} layout="vertical" onFinish={v=>uploadMutation.mutate(v)}>
        <Form.Item label="文件" required extra="图片不超过 10 MB，其他材料不超过 20 MB；支持 JPG、PNG、WebP、PDF、Word、Excel 和 TXT。">
          <Upload.Dragger accept={accept} maxCount={1} fileList={fileList} beforeUpload={()=>false} onChange={({fileList:next})=>setFileList(next.slice(-1))}>
            <p className="ant-upload-drag-icon"><InboxOutlined/></p><p className="ant-upload-text">点击或拖拽文件到此处</p><p className="ant-upload-hint">文件名与正文类型不一致时会被拒绝</p>
          </Upload.Dragger>
        </Form.Item>
        <Form.Item name="attachment_type" label="材料类型" rules={[{required:true,message:'请选择材料类型'}]}><Select options={typeOptions(user).map(value=>({value,label:typeLabels[value]}))}/></Form.Item>
        {user?.role!=='citizen'&&<Form.Item name="visibility" label="可见范围" rules={[{required:true,message:'请选择可见范围'}]}><Select options={[{value:'public',label:'公开（市民可查看）'},{value:'internal',label:'内部（仅工作人员可查看）'}]}/></Form.Item>}
      </Form>
    </Modal>
    <Modal title="删除附件" open={!!deleteTarget} onCancel={()=>setDeleteTarget(null)} onOk={()=>deleteForm.submit()} okText="确认删除" okButtonProps={{danger:true}} confirmLoading={deleteMutation.isPending} destroyOnHidden>
      <Alert type="warning" showIcon message={`删除后将停止访问“${deleteTarget?.original_filename||''}”，操作原因会进入审计日志。`} style={{marginBottom:16}}/>
      <Form form={deleteForm} layout="vertical" onFinish={v=>deleteMutation.mutate(v)}><Form.Item name="reason" label="删除原因" rules={[{required:true,message:'请填写删除原因'},{min:2,message:'至少填写 2 个字符'}]}><Input.TextArea rows={3} maxLength={500} showCount autoFocus/></Form.Item></Form>
    </Modal>
  </>
}
