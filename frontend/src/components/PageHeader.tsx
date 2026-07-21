import type { ReactNode } from 'react'
import { Typography } from 'antd'
export function PageHeader({eyebrow,title,description,extra}:{eyebrow?:string;title:string;description?:string;extra?:ReactNode}){return <div className="page-head"><div>{eyebrow&&<div className="page-eyebrow">{eyebrow}</div>}<Typography.Title level={2} className="page-title">{title}</Typography.Title>{description&&<p className="page-description">{description}</p>}</div>{extra}</div>}
