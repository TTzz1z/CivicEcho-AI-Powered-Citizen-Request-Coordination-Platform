import { Button, Tag, Collapse, Typography } from 'antd'
import { ArrowRightOutlined, CommentOutlined, SafetyCertificateOutlined, AuditOutlined, FileSearchOutlined, RobotOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'

const { Paragraph, Text } = Typography

const FEATURES = [
  {
    icon: <FileSearchOutlined style={{ fontSize: 22, color: '#167c72' }} />,
    title: '政策 RAG 检索',
    desc: '基于 pgvector 语义检索 + 关键词回退,回答必须附 title/doc_number/issuing_authority/excerpt 四要素,无证据不编造。',
  },
  {
    icon: <AuditOutlined style={{ fontSize: 22, color: '#167c72' }} />,
    title: '工单全生命周期',
    desc: '提交→受理→派发→处理→办结→评价→申诉→重办,状态机可信 + 乐观锁 + 全程审计留痕。',
  },
  {
    icon: <RobotOutlined style={{ fontSize: 22, color: '#167c72' }} />,
    title: 'Advisory AI 边界',
    desc: 'AI 仅生成建议,不调用状态变更接口。所有建议必须经工作人员三态确认(采纳/修改后采纳/驳回)。',
  },
  {
    icon: <SafetyCertificateOutlined style={{ fontSize: 22, color: '#167c72' }} />,
    title: 'AI 用量审计',
    desc: '10 种 capability 全程记录 provider/model/tokens/cost/degrade_reason,支持 session_id 筛选与降级追溯。',
  },
]

const DEMO_ACCOUNTS = [
  { role: '市民', username: 'citizen_local', hint: '提交诉求 / 政策咨询 / 评价申诉' },
  { role: '坐席', username: 'agent_local', hint: '受理派发 / 复核办结 / AI 办件助手' },
  { role: '部门人员', username: 'department_local', hint: '本部门工单处理 / KB 文档维护' },
  { role: '管理员', username: 'admin_local', hint: '用户部门分类管理 / 审计与 AI 用量' },
]

export function LandingPage() {
  return (
    <main className="landing">
      <nav className="public-nav">
        <div className="public-brand">
          <div className="brand-mark" style={{ color: '#167c72', borderColor: '#8abdb7' }}>倾</div>
          倾听助手
        </div>
        <div>
          <Link to="/login"><Button type="text">账号登录</Button></Link>
        </div>
      </nav>

      <section className="hero">
        <div>
          <Tag color="cyan"><SafetyCertificateOutlined /> 安全 · 透明 · 可追溯</Tag>
          <h1>认真倾听,<br /><span>让每一件诉求</span><br />都有回应。</h1>
          <p className="hero-copy">
            面向市民诉求受理与跨部门协同办理的政务服务演示平台。
            通过智能对话表达问题、政策 RAG 检索权威答案、工单全程可视、
            AI 建议经人工确认后方可使用。
          </p>
          <div className="hero-actions">
            <Link to="/chat"><Button size="large" type="primary" icon={<CommentOutlined />}>访客智能对话</Button></Link>
            <Link to="/login"><Button size="large">账号登录 <ArrowRightOutlined /></Button></Link>
          </div>
          <p className="visitor-hint">
            访客工单不会自动绑定后续登录账号;需要在"我的工单"中持续查看,请先登录市民账号。
          </p>

          <Collapse
            ghost
            style={{ marginTop: 32, maxWidth: 520 }}
            items={[{
              key: 'demo',
              label: <Text strong>演示账号(4 个角色)</Text>,
              children: (
                <div>
                  <Paragraph type="secondary" style={{ fontSize: 13 }}>
                    所有演示账号密码相同,由环境变量 SEED_PASSWORD 注入。
                    请勿在生产环境使用演示密码。
                  </Paragraph>
                  {DEMO_ACCOUNTS.map(acc => (
                    <div key={acc.username} style={{ padding: '6px 0', borderBottom: '1px dashed #e8e8e8' }}>
                      <Tag color="cyan">{acc.role}</Tag>
                      <Text code>{acc.username}</Text>
                      <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>{acc.hint}</Text>
                    </div>
                  ))}
                </div>
              ),
            }]}
          />
        </div>

        <div className="service-panel">
          <div className="page-eyebrow">SERVICE FLOW · 服务闭环</div>
          <h2 className="service-title">从诉求提交到结果反馈</h2>
          <div className="service-list">
            {[
              ['01 表达诉求', '智能助手引导补充类型、地点、时间等必要信息'],
              ['02 协同办理', '坐席受理并派发至责任部门,状态实时流转'],
              ['03 进度透明', '每一步操作留痕,市民可随时查看办理进展'],
              ['04 结果反馈', '部门填写处置意见,最终办结并对外展示'],
            ].map(x => (
              <div className="service-row" key={x[0]}><b>{x[0]}</b><span>{x[1]}</span></div>
            ))}
          </div>
        </div>
      </section>

      <section style={{ maxWidth: 1200, margin: '64px auto 48px', padding: '0 24px' }}>
        <div className="page-eyebrow">CORE CAPABILITIES · 核心能力</div>
        <h2 style={{ fontSize: 28, marginBottom: 32 }}>贴近真实政务平台的工程实现</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 24 }}>
          {FEATURES.map(f => (
            <div key={f.title} style={{
              padding: 24, background: '#fff', border: '1px solid #e8e8e8',
              borderRadius: 8, boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
            }}>
              <div style={{ marginBottom: 12 }}>{f.icon}</div>
              <h3 style={{ fontSize: 16, marginBottom: 8, fontWeight: 600 }}>{f.title}</h3>
              <Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 0, lineHeight: 1.7 }}>
                {f.desc}
              </Paragraph>
            </div>
          ))}
        </div>
        <Paragraph type="secondary" style={{ marginTop: 32, fontSize: 12, textAlign: 'center' }}>
          本项目为工程演示作品,所有数据为演示种子数据,不接入真实政务系统。
        </Paragraph>
      </section>
    </main>
  )
}
