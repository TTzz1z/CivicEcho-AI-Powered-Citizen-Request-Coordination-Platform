import { api } from './client'
import type { ApiSuccess, AuditPage, Category, Dashboard, Department, Role, User, UserFilters, UserPage } from '../types'
export async function listUsers(){const page=(await api.get<ApiSuccess<UserPage>>('/users',{params:{page_size:100}})).data.data;return page.items}
export async function listUsersPage(filters:UserFilters={}){return (await api.get<ApiSuccess<UserPage>>('/users',{params:filters})).data.data}
export async function createUser(data:{username:string;password:string;display_name:string;role:Role;department_id?:number;is_active:boolean}){return (await api.post<ApiSuccess<User>>('/users',data)).data.data}
export async function updateUser(id:number,data:Partial<Omit<User,'id'|'username'>> & {password?:string}){return (await api.patch<ApiSuccess<User>>(`/users/${id}`,data)).data.data}
export async function listDepartments(){return (await api.get<ApiSuccess<Department[]>>('/departments')).data.data}
export async function listDepartmentStaff(departmentId:number){return (await api.get<ApiSuccess<User[]>>(`/departments/${departmentId}/staff`)).data.data}
export async function createDepartment(data:{code:string;name:string;description?:string}){return (await api.post<ApiSuccess<Department>>('/departments',data)).data.data}
export async function updateDepartment(id:number,data:Partial<Pick<Department,'name'|'description'|'is_active'>>){return (await api.patch<ApiSuccess<Department>>(`/departments/${id}`,data)).data.data}
export async function listCategories(){return (await api.get<ApiSuccess<Category[]>>('/categories')).data.data}
export async function createCategory(data:{code:string;name:string;parent_id?:number;default_department_id?:number;accept_sla_minutes:number;resolve_sla_minutes:number}){return (await api.post<ApiSuccess<Category>>('/categories',data)).data.data}
export async function updateCategory(id:number,data:Partial<Omit<Category,'id'|'code'|'level'|'default_department_name'>>){return (await api.patch<ApiSuccess<Category>>(`/categories/${id}`,data)).data.data}
export async function getDashboard(){return (await api.get<ApiSuccess<Dashboard>>('/admin/dashboard')).data.data}
export async function getAuditLogs(page=1,pageSize=20,action?:string){return (await api.get<ApiSuccess<AuditPage>>('/admin/audit-logs',{params:{page,page_size:pageSize,action:action||undefined}})).data.data}
