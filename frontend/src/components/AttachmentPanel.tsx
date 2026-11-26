import { DeleteOutlined, DownloadOutlined, EyeInvisibleOutlined, FileProtectOutlined, InboxOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Drawer, Empty, Form, Input, List, Modal, Select, Space, Spin, Tag, Typography, Upload, message, type UploadFile } from 'antd'
import dayjs from 'dayjs'
import { lazy, Suspense, useEffect, useState } from 'react'
import { attachmentKeys, canPreviewAttachment, deleteAttachment, downloadAttachment, listAttachments, loadAttachmentPreview, uploadAttachment } from '../api/attachments'
import { ApiError } from '../api/client'
import type { AttachmentType, AttachmentVisibility, TicketAttachment, TicketStatus, User } from '../types'

const typeLabels:Record<AttachmentType,string>={citizen_material:'市民补充材料',site_photo:'现场照片',official_document:'办理文书',processing_proof:'处理证明',other:'其他材料'}
const accept='.jpg,.jpeg,.png,.webp,.pdf,.doc,.docx,.xls,.xlsx,.txt'
const PdfPreview = lazy(() => import('./AttachmentPdfPreview'))
const scanLabels: Record<string, { color: string; text: string }> = {
  clean: { color: 'green', text: '扫描通过' },
  skipped: { color: 'default', text: '未扫描' },
  pending: { color: 'processing', text: '等待扫描' },
  infected: { color: 'red', text: '未通过扫描' },
  error: { color: 'warning', text: '扫描失败' },
}

function AttachmentPreview({ item }: { item: TicketAttachment }) {
  const [file, setFile] = useState<Blob | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const request = new AbortController()
    let url = ''
    void loadAttachmentPreview(item, request.signal).then(blob => {
      if (request.signal.aborted) return
      if (item.content_type === 'application/pdf') setFile(blob)
      else {
        url = URL.createObjectURL(blob)
        setImageUrl(url)
      }
    }).catch(cause => {
      if (!request.signal.aborted) setError(cause instanceof Error ? cause.message : '预览加载失败')
    })
    return () => {
      request.abort()
      if (url) URL.revokeObjectURL(url)
    }
  }, [item, attempt])

  if (error) return <Alert type="warning" showIcon message={error}
    action={<Button onClick={() => { setError(''); setImageUrl(''); setAttempt(value => value + 1) }}>重试</Button>} />
  const loading = <Spin aria-label="正在加载附件预览" />
  if (file) return <Suspense fallback={loading}><PdfPreview file={file} filename={item.original_filename} /></Suspense>
  if (imageUrl) return <img src={imageUrl} className="attachment-preview-image"
    alt={item.original_filename} onError={() => setError('图片无法显示，请使用下载')} />
  return loading
}

function formatBytes(bytes:number){if(bytes<1024)return `${bytes} B`;if(bytes<1024*1024)return `${(bytes/1024).toFixed(1)} KB`;return `${(bytes/1024/1024).toFixed(1)} MB`}
function typeOptions(user:User|null){
  if(user?.role==='citizen')return ['citizen_material','other'] as AttachmentType[]
  if(user?.role==='department_staff')return ['site_photo','official_document','processing_proof','other'] as AttachmentType[]
  return ['citizen_material','site_photo','official_document','processing_proof','other'] as AttachmentType[]
}

export function AttachmentPanel({ticketId,status,user}:{ticketId:string;status:TicketStatus;user:User|null}){
  const qc=useQueryClient();const [uploadOpen,setUploadOpen]=useState(false);const [deleteTarget,setDeleteTarget]=useState<TicketAttachment|null>(null)
  const [preview, setPreview] = useState<TicketAttachment | null>(null)
  const [fileError, setFileError] = useState('')
  const [fileList,setFileList]=useState<UploadFile[]>([]);const [uploadForm]=Form.useForm<{attachment_type:AttachmentType;visibility:AttachmentVisibility}>();const [deleteForm]=Form.useForm<{reason:string}>()
  const query=useQuery({queryKey:attachmentKeys.ticket(ticketId),queryFn:()=>listAttachments(ticketId)})
  const uploadMutation=useMutation({mutationFn:async(v:{attachment_type:AttachmentType;visibility:AttachmentVisibility})=>{
    const file=fileList[0]?.originFileObj;if(!file)throw new Error('请选择要上传的文件')
    return uploadAttachment(ticketId,file,v.attachment_type,user?.role==='citizen'?'public':v.visibility)
  },onSuccess:()=>{message.success('附件已完成校验并上传');setUploadOpen(false);setFileList([]);uploadForm.resetFields();void qc.invalidateQueries({queryKey:attachmentKeys.ticket(ticketId)})},onError:e=>message.error(e instanceof Error?e.message:'附件上传失败')})
  const deleteMutation=useMutation({mutationFn:(v:{reason:string})=>deleteAttachment(deleteTarget!.id,v.reason),onSuccess:()=>{message.success('附件已删除并记录审计');setDeleteTarget(null);deleteForm.resetFields();void qc.invalidateQueries({queryKey:attachmentKeys.ticket(ticketId)})},onError:e=>message.error(e instanceof Error?e.message:'附件删除失败')})
  const canUpload=!!user&&!(user.role==='citizen'&&['closed','rejected'].includes(status))
  const openUpload=()=>{setFileList([]);setFileError('');uploadForm.setFieldsValue({attachment_type:user?.role==='citizen'?'citizen_material':'site_photo',visibility:'public'});setUploadOpen(true)}
  const startDownload=async(item:TicketAttachment)=>{try{await downloadAttachment(item)}catch(e){message.error(e instanceof ApiError?e.message:'附件下载失败')}}
  return <>
    <Card className="surface detail-card attachment-panel" style={{marginTop:20}} title={<Space><FileProtectOutlined/>附件与办理证据</Space>} extra={canUpload?<Button type="primary" onClick={openUpload}>上传附件</Button>:null}>
      <Alert className="attachment-guidance" type="info" showIcon message={user?.role==='citizen'?'公开附件将随工单提供给办理人员；请勿上传无关隐私信息。':'标记为“内部”的附件不会向市民展示。文件通过安全校验后才会保存。'}/>
      {query.isError?<Alert type="error" showIcon message={query.error instanceof Error?query.error.message:'附件加载失败'} action={<Button size="small" onClick={()=>query.refetch()}>重试</Button>}/>:query.isLoading?<Card loading bordered={false}/>:query.data?.items.length?<List className="attachment-list" dataSource={query.data.items} renderItem={item=><List.Item actions={[
        canPreviewAttachment(item) ? <Button key="preview" type="text" aria-label={`预览 ${item.original_filename}`} onClick={() => setPreview(item)}>预览</Button> : null,
        <Button key="download" type="text" icon={<DownloadOutlined/>} aria-label={`下载 ${item.original_filename}`} onClick={()=>void startDownload(item)}>下载</Button>,
        (user?.role==='admin'||user?.role==='department_staff'||item.uploader_user_id===user?.id)?<Button key="delete" type="text" danger icon={<DeleteOutlined/>} aria-label={`删除 ${item.original_filename}`} onClick={()=>{deleteForm.resetFields();setDeleteTarget(item)}}>删除</Button>:null,
      ].filter(Boolean)}><List.Item.Meta avatar={<div className="attachment-icon"><FileProtectOutlined/></div>} title={<Space wrap><span className="attachment-filename">{item.original_filename}</span><Tag>{typeLabels[item.attachment_type]}</Tag>{item.visibility==='internal'&&<Tag icon={<EyeInvisibleOutlined/>} color="gold">内部</Tag>}<Tag icon={<SafetyCertificateOutlined/>} color={scanLabels[item.scan_status]?.color}>{scanLabels[item.scan_status]?.text ?? '扫描状态未知'}</Tag></Space>} description={`${formatBytes(item.size_bytes)} · ${dayjs(item.created_at).format('YYYY-MM-DD HH:mm')} · SHA-256 ${item.sha256.slice(0,12)}…`}/></List.Item>}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无附件或办理证据"/>}
    </Card>
    <Drawer title="附件预览" open={!!preview} onClose={() => setPreview(null)} size="min(800px, 100vw)"
      extra={preview && <Button icon={<DownloadOutlined />} onClick={() => void startDownload(preview)}>下载原件</Button>}>
      {preview && <>
        <Typography.Title level={4} className="attachment-filename">{preview.original_filename}</Typography.Title>
        <AttachmentPreview key={preview.id} item={preview} />
      </>}
    </Drawer>
    <Modal title="上传附件与办理证据" open={uploadOpen} onCancel={()=>setUploadOpen(false)} onOk={()=>uploadForm.submit()} okText="校验并上传" confirmLoading={uploadMutation.isPending} destroyOnHidden>
      <Form form={uploadForm} layout="vertical" onFinish={v=>uploadMutation.mutate(v)}>
        <Form.Item label="文件" required extra="图片不超过 10 MB，其他材料不超过 20 MB。支持 JPG、PNG、WebP、PDF、Word、Excel 和 TXT。"
          validateStatus={fileError ? 'error' : undefined} help={fileError || undefined}>
          <Upload.Dragger accept={accept} maxCount={1} fileList={fileList} beforeUpload={file => {
            const extension = file.name.match(/\.[^.]+$/)?.[0].toLowerCase() ?? ''
            const max = ['.jpg', '.jpeg', '.png', '.webp'].includes(extension) ? 10 : 20
            if (!accept.split(',').includes(extension) || file.size > max * 1024 * 1024 || file.size === 0) {
              setFileList([])
              setFileError(!accept.split(',').includes(extension) ? '请选择支持的文件类型' : file.size === 0 ? '请选择非空文件' : `文件超过 ${max} MB`)
              return Upload.LIST_IGNORE
            }
            setFileError('')
            return false
          }} onChange={({fileList:next})=>setFileList(next.slice(-1))}>
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
