import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { WorkspaceLayout } from '../layouts/WorkspaceLayout'
import { ForbiddenPage, NotFoundPage } from '../pages/ResultPages'
import { HomeRedirect, RequireAuth, RequireRole } from './guards'
import { PageLoading } from '../components/PageState'

const LandingPage=lazy(()=>import('../pages/LandingPage').then(m=>({default:m.LandingPage})))
const LoginPage=lazy(()=>import('../pages/LoginPage').then(m=>({default:m.LoginPage})))
const OidcCallbackPage=lazy(()=>import('../pages/OidcCallbackPage').then(m=>({default:m.OidcCallbackPage})))
const ChatPage=lazy(()=>import('../pages/ChatPage').then(m=>({default:m.ChatPage})))
const TicketsPage=lazy(()=>import('../pages/TicketsPage').then(m=>({default:m.TicketsPage})))
const TicketDetailPage=lazy(()=>import('../pages/TicketDetailPage').then(m=>({default:m.TicketDetailPage})))
const DashboardPage=lazy(()=>import('../pages/DashboardPage').then(m=>({default:m.DashboardPage})))
const UsersPage=lazy(()=>import('../pages/UsersPage').then(m=>({default:m.UsersPage})))
const DepartmentsPage=lazy(()=>import('../pages/DepartmentsPage').then(m=>({default:m.DepartmentsPage})))
const AuditPage=lazy(()=>import('../pages/AuditPage').then(m=>({default:m.AuditPage})))
const CategoriesPage=lazy(()=>import('../pages/CategoriesPage').then(m=>({default:m.CategoriesPage})))
const NotificationsPage=lazy(()=>import('../pages/NotificationsPage').then(m=>({default:m.NotificationsPage})))
const AftercarePage=lazy(()=>import('../pages/AftercarePage').then(m=>({default:m.AftercarePage})))
const IntelligencePage=lazy(()=>import('../pages/IntelligencePage').then(m=>({default:m.IntelligencePage})))
const CitizenPolicyPage=lazy(()=>import('../pages/CitizenPolicyPage').then(m=>({default:m.CitizenPolicyPage})))
const AgentPolicyPage=lazy(()=>import('../pages/AgentPolicyPage').then(m=>({default:m.AgentPolicyPage})))
const DepartmentKbPage=lazy(()=>import('../pages/DepartmentKbPage').then(m=>({default:m.DepartmentKbPage})))
const AdminKbPage=lazy(()=>import('../pages/AdminKbPage').then(m=>({default:m.AdminKbPage})))
const AdminAiUsagePage=lazy(()=>import('../pages/AdminAiUsagePage').then(m=>({default:m.AdminAiUsagePage})))
const loading=<PageLoading/>

export function AppRoutes(){return <Suspense fallback={loading}><Routes>
  <Route path="/welcome" element={<LandingPage/>}/><Route path="/login" element={<LoginPage/>}/><Route path="/auth/oidc/callback" element={<OidcCallbackPage/>}/><Route path="/chat" element={<div className="public-chat-page"><ChatPage/></div>}/><Route path="/forbidden" element={<ForbiddenPage/>}/>
  <Route element={<RequireAuth/>}><Route element={<WorkspaceLayout/>}><Route path="/" element={<HomeRedirect/>}/>
    <Route element={<RequireRole roles={['citizen']}/>}><Route path="/citizen/chat" element={<ChatPage/>}/><Route path="/citizen/tickets" element={<TicketsPage/>}/><Route path="/citizen/tickets/:ticketId" element={<TicketDetailPage/>}/><Route path="/citizen/policy" element={<CitizenPolicyPage/>}/><Route path="/citizen/intelligence" element={<IntelligencePage/>}/><Route path="/citizen/notifications" element={<NotificationsPage/>}/><Route path="/citizen/aftercare" element={<AftercarePage/>}/></Route>
    <Route element={<RequireRole roles={['agent']}/>}><Route path="/agent/tickets" element={<TicketsPage/>}/><Route path="/agent/tickets/:ticketId" element={<TicketDetailPage/>}/><Route path="/agent/policy" element={<AgentPolicyPage/>}/><Route path="/agent/intelligence" element={<IntelligencePage/>}/><Route path="/agent/notifications" element={<NotificationsPage/>}/><Route path="/agent/aftercare" element={<AftercarePage/>}/></Route>
    <Route element={<RequireRole roles={['department_staff', 'admin']}/>}><Route path="/department/tickets" element={<TicketsPage/>}/><Route path="/department/tickets/:ticketId" element={<TicketDetailPage/>}/><Route path="/department/kb" element={<DepartmentKbPage/>}/><Route path="/department/intelligence" element={<IntelligencePage/>}/><Route path="/department/notifications" element={<NotificationsPage/>}/><Route path="/department/aftercare" element={<AftercarePage/>}/></Route>
    <Route element={<RequireRole roles={['admin']}/>}><Route path="/admin/dashboard" element={<DashboardPage/>}/><Route path="/admin/tickets" element={<TicketsPage/>}/><Route path="/admin/tickets/:ticketId" element={<TicketDetailPage/>}/><Route path="/admin/kb" element={<AdminKbPage/>}/><Route path="/admin/ai-usage" element={<AdminAiUsagePage/>}/><Route path="/admin/intelligence" element={<IntelligencePage/>}/><Route path="/admin/notifications" element={<NotificationsPage/>}/><Route path="/admin/aftercare" element={<AftercarePage/>}/><Route path="/admin/categories" element={<CategoriesPage/>}/><Route path="/admin/users" element={<UsersPage/>}/><Route path="/admin/departments" element={<DepartmentsPage/>}/><Route path="/admin/audit" element={<AuditPage/>}/></Route>
  </Route></Route><Route path="*" element={<NotFoundPage/>}/>
</Routes></Suspense>}
