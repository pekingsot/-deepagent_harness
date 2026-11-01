export interface AuthUser {
  id: number; // 整数用户主键
  tenant_id: number; // 所属租户主键
  tenant_code: string; // 公司登录代码
  tenant_name: string; // 公司名称
  project_id: string; // 默认工作空间
  username: string; // 登录名
  display_name: string; // 显示名称
  role: "admin" | "user"; // 租户内角色
}

export interface ManagedUser {
  id: number; // 整数用户主键
  username: string; // 登录名
  display_name: string; // 显示名称
  role: "admin" | "user"; // 账号角色
  enabled: boolean; // 是否启用
  created_at: string; // 创建时间
  last_login_at: string | null; // 最近登录时间
}

export interface UserPage {
  items: ManagedUser[]; // 当前分页
  next_cursor: number | null; // 下一页游标
}
