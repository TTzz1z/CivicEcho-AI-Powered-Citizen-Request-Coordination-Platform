import { Alert, Button, Space, Spin } from 'antd'
import { useEffect, useRef, useState } from 'react'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'

const previewWidth = 1200
const previewPixels = 3_000_000

export default function AttachmentPdfPreview({ file, filename }: { file: Blob; filename: string }) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [page, setPage] = useState(1)
  const [error, setError] = useState(false)
  const [rendering, setRendering] = useState(true)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    let disposed = false
    let task: ReturnType<typeof import('pdfjs-dist')['getDocument']> | undefined

    async function load() {
      const [pdfjs, buffer] = await Promise.all([import('pdfjs-dist/legacy/build/pdf.mjs'), file.arrayBuffer()])
      if (disposed) return
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
      task = pdfjs.getDocument({
        data: new Uint8Array(buffer),
        enableXfa: false,
        useWasm: false,
        maxImageSize: 16_000_000,
      })
      const loaded = await task.promise
      if (!disposed) setDocument(loaded)
    }

    void load().catch(() => { if (!disposed) setError(true) })
    return () => {
      disposed = true
      void task?.destroy().catch(() => undefined)
    }
  }, [file])

  useEffect(() => {
    if (!document) return
    let disposed = false
    let render: RenderTask | undefined
    setRendering(true)
    setError(false)

    async function draw(pdf: PDFDocumentProxy) {
      const sheet = await pdf.getPage(page)
      const canvas = canvasRef.current
      if (disposed || !canvas) return
      const layout = sheet.getViewport({ scale: 1 })
      if (!(layout.width > 0 && layout.height > 0)) throw new Error('Invalid PDF page size')
      const scale = Math.min(2, previewWidth / layout.width, Math.sqrt(previewPixels / (layout.width * layout.height)))
      const viewport = sheet.getViewport({ scale })
      canvas.width = Math.max(1, Math.floor(viewport.width))
      canvas.height = Math.max(1, Math.floor(viewport.height))
      render = sheet.render({ canvas, viewport })
      await render.promise
      if (!disposed) setRendering(false)
    }

    void draw(document).catch(() => {
      if (!disposed) { setError(true); setRendering(false) }
    })
    return () => { disposed = true; render?.cancel() }
  }, [document, page])

  return <>
    {document && <Space wrap className="attachment-preview-controls">
      <Button disabled={page === 1 || rendering} onClick={() => setPage(page - 1)}>上一页</Button>
      <span role="status">第 {page} 页，共 {document.numPages} 页</span>
      <Button disabled={page >= document.numPages || rendering} onClick={() => setPage(page + 1)}>下一页</Button>
    </Space>}
    {error ? <Alert type="warning" showIcon message="这份 PDF 无法预览，请使用下载。" /> : rendering && <Spin aria-label="正在生成 PDF 预览" />}
    <canvas className="attachment-preview-canvas" ref={canvasRef} hidden={rendering || error}
      role="img" aria-label={`${filename}，第 ${page} 页`} />
  </>
}
