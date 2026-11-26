import { useRef, useState, type KeyboardEvent } from 'react'
import { Button } from 'antd'
import { ArrowRightOutlined, CommentOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { BrandMark } from '../components/BrandMark'
import { demoMode } from '../demoMode'
import '../styles/landing.css'

const DEMO_ACCOUNTS = [
  { role: '市民端', key: 'citizen', username: 'citizen_local', hint: '对话登记 · 草稿核对 · 进度评价' },
  { role: '坐席端', key: 'agent', username: 'agent_local', hint: '智能分诊 · 三态审核 · 受理派发' },
  { role: '部门端', key: 'department', username: 'department_local', hint: 'SLA 队列 · 协同汇总 · AI 办件' },
  { role: '管理端', key: 'admin', username: 'admin_local', hint: '运营趋势 · 风险雷达 · 审计追溯' },
]

const STAGES = [
  {
    tab: '01 市民表达',
    eyebrow: '01 · CITIZEN CONVERSATIONAL INTAKE',
    rightTitle: 'STRUCTURED DRAFT · 3/3',
    rows: [
      ['诉求类型', '求助 · 公共照明'],
      ['发生地点', '幸福路社区 3 号楼'],
      ['必填校验', '100% 已齐备'],
    ],
    ctaLabel: '进入访客智能对话 →',
    ctaTo: '/chat',
    body: (
      <>
        <div className="ce-quote-bubble">
          “幸福路社区 3 号楼旁路灯连续三天未亮，夜间通行存在安全隐患。”
        </div>
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7, color: 'var(--ce-muted)' }}>
          系统自动识别诉求类型、发生地点与持续时长，并生成规范化文本，由市民核对确认后正式提交建单。
        </p>
      </>
    ),
  },
  {
    tab: '02 智能分诊',
    eyebrow: '02 · ADVISORY AI TRIAGE & HUMAN GATE',
    rightTitle: 'HUMAN REVIEW BOUNDARY',
    rows: [
      ['信息完整性', '92%'],
      ['紧急程度', '加急 · Expedited'],
      ['自动派发', '已禁止（人工确认）'],
    ],
    ctaLabel: '登录坐席工作台 →',
    ctaTo: '/login?demo=agent',
    body: (
      <div style={{ display: 'grid', gap: 12 }}>
        <div className="ce-bar-row">
          <div className="ce-bar-head"><strong>推荐 1：综合受理</strong><span className="workspace-reference">94%</span></div>
          <div className="ce-bar-track"><div className="ce-bar-fill" style={{ width: '94%' }} /></div>
        </div>
        <div className="ce-bar-row">
          <div className="ce-bar-head"><span style={{ color: 'var(--ce-muted)' }}>推荐 2：城市管理</span><span className="workspace-reference">89%</span></div>
          <div className="ce-bar-track"><div className="ce-bar-fill muted" style={{ width: '89%' }} /></div>
        </div>
        <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ce-muted)' }}>
          AI 仅提供只读分诊建议；坐席核对原文后执行「原样采纳 / 修改后采纳 / 拒绝」，受理与派发仍在工单详情人工完成。
        </p>
      </div>
    ),
  },
  {
    tab: '03 协同办理',
    eyebrow: '03 · MULTI-DEPARTMENT WORK ORDER',
    rightTitle: 'SLA & COLLABORATION',
    rows: [
      ['当前状态', 'processing'],
      ['协同阶段', 'awaiting_review'],
      ['答复约束', '事实核实 + 占位符模板'],
    ],
    ctaLabel: '登录部门工作台 →',
    ctaTo: '/login?demo=department',
    body: (
      <div style={{ display: 'grid', gap: 12 }}>
        <div className="ce-mini-cards">
          <div className="ce-mini-card">
            <strong>主办 · 综合受理</strong>
            <span style={{ color: 'var(--ce-success)' }}>● 已汇总送审</span>
          </div>
          <div className="ce-mini-card">
            <strong>协办 · 城市管理</strong>
            <span style={{ color: 'var(--ce-accent)' }}>● 现场已完成修复</span>
          </div>
        </div>
        <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ce-muted)' }}>
          部门按 SLA 时限核查处置，AI 办件助手生成核查清单与合规回复模板，未填真实事实时不虚构办结结果。
        </p>
      </div>
    ),
  },
  {
    tab: '04 办结审计',
    eyebrow: '04 · PUBLIC CLOSURE & AUDIT TRACE',
    rightTitle: 'OPS & GOVERNANCE',
    rows: [
      ['办结方式', '市民确认满意 · closed'],
      ['14 日趋势', '北京时间自然日聚合'],
      ['AI 用量审计', '全链路记录 Token / 降级'],
    ],
    ctaLabel: '登录运营管理台 →',
    ctaTo: '/login?demo=admin',
    body: (
      <div style={{ display: 'grid', gap: 12 }}>
        <div style={{ paddingLeft: 12, borderLeft: '2px solid var(--ce-ink)', fontSize: 13.5, lineHeight: 1.7, color: 'var(--ce-ink-2)' }}>
          “经运维班组现场排查，已更换防水接线盒并完成通电测试，路灯照明已恢复正常。”
        </div>
        <div className="ce-state-meta" style={{ marginTop: 0, paddingTop: 8 }}>
          <span style={{ color: 'var(--ce-success)' }}>● citizen_confirmed</span>
          <span>lock_version: v5 · audit_logs 已落库</span>
        </div>
      </div>
    ),
  },
]

export function LandingPage() {
  const [stageIdx, setStageIdx] = useState(0)
  const tabs = useRef<(HTMLButtonElement | null)[]>([])

  function changeStage(event: KeyboardEvent, index: number) {
    const last = STAGES.length - 1
    let next: number
    switch (event.key) {
      case 'ArrowRight': next = index === last ? 0 : index + 1; break
      case 'ArrowLeft': next = index === 0 ? last : index - 1; break
      case 'Home': next = 0; break
      case 'End': next = last; break
      default: return
    }
    event.preventDefault()
    setStageIdx(next)
    tabs.current[next]?.focus()
  }

  return (
    <main className="ce-landing">
      <div className="ce-landing-hero-wrap">
        <div className="ce-landing-dots" aria-hidden="true" />
        <nav className="ce-landing-nav" aria-label="服务首页导航">
          <div className="ce-landing-nav-inner">
            <Link to="/welcome" className="ce-landing-brand">
              <BrandMark size={24} />
              <span>倾听助手</span>
              <span className="ce-landing-brand-en">CivicEcho</span>
            </Link>
            <div className="ce-landing-nav-actions">
              <Button href="/login" type="text">账号登录</Button>
              <Button href="/chat" type="primary">{demoMode ? '开始体验' : '访客对话'}</Button>
            </div>
          </div>
        </nav>

        <section className="ce-landing-hero">
          <div className="ce-landing-pill">
            <span className="ce-status-dot tone-ok" aria-hidden="true" />
            <span>{demoMode ? '市民诉求受理与跨部门协同演示平台' : '市民诉求受理与跨部门协同'}</span>
            <span className="ce-landing-pill-sep">|</span>
            <span className="ce-landing-pill-tag">Advisory AI</span>
          </div>

          <h1 className="ce-landing-title">
            认真倾听，
            <span className="ce-landing-title-sub">让每一件诉求都有回应。</span>
          </h1>

          <p className="ce-landing-lead">
            通过对话登记诉求、查询政策依据。登录后可在「我的工单」查看办理进度和答复。
          </p>

          <div className="ce-landing-cta">
            <Button href="/chat" size="large" type="primary" icon={<CommentOutlined />}>访客智能对话</Button>
            <Button href="/login" size="large">账号登录 <ArrowRightOutlined /></Button>
          </div>

          <p className="ce-landing-visitor-note">
            登录市民账号后，系统会尝试将本浏览器中的访客会话工单绑定到该账号；若需全程在“我的工单”跟踪，建议先登录再提交。
          </p>

          {demoMode && <div className="ce-showcase" aria-label="工单全生命周期交互演示">
            <div className="ce-showcase-chrome">
              <div className="ce-showcase-meta">
                <div className="ce-window-dots" aria-hidden="true"><span /><span /><span /></div>
                <span className="ce-showcase-id">
                  <span className="ce-status-dot tone-ok" aria-hidden="true" />
                  QT2026111500000224 · 演示闭环
                </span>
              </div>
              <div className="ce-stage-tabs" role="tablist" aria-label="服务闭环阶段">
                {STAGES.map((item, idx) => (
                  <button
                    key={item.tab}
                    type="button"
                    role="tab"
                    id={`showcase-tab-${idx}`}
                    ref={element => { tabs.current[idx] = element }}
                    aria-selected={stageIdx === idx}
                    tabIndex={stageIdx === idx ? 0 : -1}
                    className="ce-stage-tab"
                    onClick={() => setStageIdx(idx)}
                    onKeyDown={event => changeStage(event, idx)}
                  >
                    {item.tab}
                  </button>
                ))}
              </div>
            </div>
            {STAGES.map((stage, idx) => <div key={stage.tab} role="tabpanel" aria-labelledby={`showcase-tab-${idx}`} hidden={stageIdx !== idx}>
            <div className="ce-showcase-body">
              <div className="ce-showcase-left">
                <div className="ce-micro-eyebrow">{stage.eyebrow}</div>
                {stage.body}
              </div>
              <div className="ce-showcase-right">
                <div>
                  <div className="ce-micro-eyebrow muted" style={{ marginBottom: 10 }}>{stage.rightTitle}</div>
                  <ul className="ce-kv-list">
                    {stage.rows.map(([k, v]) => (
                      <li key={k}><span>{k}</span><strong>{v}</strong></li>
                    ))}
                  </ul>
                </div>
                <Link className="ce-showcase-link" to={stage.ctaTo}>{stage.ctaLabel}</Link>
              </div>
            </div>
            </div>)}
          </div>}
        </section>
      </div>

      {demoMode && <section className="ce-bento-band" aria-labelledby="public-capabilities-title">
        <div className="ce-bento-inner">
          <div className="ce-bento-head">
            <div>
              <div className="ce-micro-eyebrow">ENGINEERING ARCHITECTURE</div>
              <h2 id="public-capabilities-title">贴近真实政务平台的工程实现</h2>
            </div>
            <span className="ce-bento-stack">React 18 · TypeScript · FastAPI · PostgreSQL / pgvector</span>
          </div>

          <div className="ce-bento-grid">
            <article className="ce-bento-card">
              <div>
                <div className="ce-bento-title-row">
                  <h3>政策 RAG 证据溯源</h3>
                  <span className="ce-bento-tag">pgvector + pg_trgm</span>
                </div>
                <p>语义检索叠加关键词回退，每条回答附文号、发文机关与原文摘录，无证据时直接说明不编造。</p>
              </div>
              <div className="ce-diagram-box">
                <div className="ce-bento-title-row">
                  <strong style={{ color: 'var(--ce-ink)' }}>路灯报修指南（虚构示例）</strong>
                  <span className="ce-bento-tag accent">引用展示示例</span>
                </div>
                <div className="ce-rag-excerpt">“登记时请写明路灯所在道路、最近地标及故障现象。”</div>
              </div>
            </article>

            <article className="ce-bento-card">
              <div>
                <div className="ce-bento-title-row">
                  <h3>可信状态机与乐观锁</h3>
                  <span className="ce-bento-tag">AuthorizationPolicy</span>
                </div>
                <p>业务状态流转与角色权限由后端策略强控，携带版本号防并发覆盖，全链路写入审计日志。</p>
              </div>
              <div className="ce-diagram-box">
                <div className="ce-state-flow">
                  <span className="ce-state-node">pending</span>
                  <span>→</span>
                  <span className="ce-state-node">accepted</span>
                  <span>→</span>
                  <span className="ce-state-node dark">processing</span>
                  <span>→</span>
                  <span className="ce-state-node accent">resolved</span>
                  <span>→</span>
                  <span className="ce-state-node ok">closed</span>
                </div>
                <div className="ce-state-meta">
                  <span>lock_version: v3 → v4</span>
                  <span style={{ color: 'var(--ce-success)' }}>✓ audit_logs committed</span>
                </div>
              </div>
            </article>

            <article className="ce-bento-card ai-shimmer">
              <div>
                <div className="ce-bento-title-row">
                  <h3>Advisory AI 三态人工审核边界</h3>
                  <span className="ce-bento-tag accent">advisory_only = true</span>
                </div>
                <p>AI 仅生成只读建议，绝不越权调用受理、派发或办结接口；人工采纳、修订或拒绝均独立留痕。</p>
              </div>
              <div className="ce-diagram-box">
                <div className="ce-gate-grid">
                  <div className="ce-gate-box">
                    <div className="ce-bento-tag accent">AI SUGGESTION</div>
                    <strong style={{ display: 'block', marginTop: 4 }}>推荐：综合受理</strong>
                    <span className="ce-bento-tag">只读 · 不改业务表</span>
                  </div>
                  <div style={{ textAlign: 'center', fontSize: 11, color: 'var(--ce-tertiary)' }}>人工闸门 →</div>
                  <div className="ce-gate-box dark">
                    <div className="ce-bento-tag" style={{ color: '#a1a1aa' }}>HUMAN COMMIT</div>
                    <strong style={{ display: 'block', marginTop: 4 }}>采纳 / 修订 / 拒绝</strong>
                    <span style={{ fontSize: 11, color: '#34d399' }}>人工前往详情办理</span>
                  </div>
                </div>
              </div>
            </article>

            <article className="ce-bento-card">
              <div>
                <div className="ce-bento-title-row">
                  <h3>AI 用量审计与无感降级</h3>
                  <span className="ce-bento-tag">10 capabilities</span>
                </div>
                <p>按能力类型全链路记录模型、Token、成本估算与降级原因；无密钥或超预算时优雅回退规则引擎。</p>
              </div>
              <div className="ce-diagram-box">
                <div className="ce-sparkline-wrap">
                  <div className="ce-spark-bars" aria-hidden="true">
                    <span style={{ height: 14 }} />
                    <span style={{ height: 22 }} />
                    <span style={{ height: 18 }} />
                    <span style={{ height: 30, background: 'rgba(37,99,235,0.55)' }} />
                    <span style={{ height: 26, background: 'rgba(37,99,235,0.75)' }} />
                    <span style={{ height: 38, background: '#2563eb' }} />
                    <span style={{ height: 24, background: '#10b981' }} />
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="workspace-reference" style={{ fontWeight: 600, color: 'var(--ce-ink)' }}>deepseek-chat → rules</div>
                    <div className="ce-bento-tag" style={{ marginTop: 4 }}>支持 session_id 筛选与降级追溯</div>
                  </div>
                </div>
              </div>
            </article>
          </div>

          <div className="ce-roles-panel" aria-label="默认演示账号">
            <div className="ce-roles-head">
              <strong>默认演示账号（四角色闭环）</strong>
              <span className="ce-bento-tag">点击前往登录并预填对应角色用户名</span>
            </div>
            <div className="ce-roles-grid">
              {DEMO_ACCOUNTS.map((acc) => (
                <Link key={acc.username} to={`/login?demo=${acc.key}`} className="ce-role-tile">
                  <div className="ce-role-tile-top">
                    <span>{acc.role}</span>
                    <span style={{ color: 'var(--ce-tertiary)' }}>→</span>
                  </div>
                  <span className="ce-role-tile-code">{acc.username}</span>
                  <span className="ce-role-tile-desc">{acc.hint}</span>
                </Link>
              ))}
            </div>
          </div>

          <footer className="ce-landing-footer">
            <span>倾听助手 CivicEcho · 政务诉求协同演示平台</span>
            <span>工程演示项目 · 所有数据均为演示种子数据，不接入真实政务系统</span>
          </footer>
        </div>
      </section>}
    </main>
  )
}
