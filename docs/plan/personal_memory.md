# 个人中心：长期记忆管理

## 使用入口

点击工作台左下角头像，选择“个人中心”。默认显示“长期记忆”页签；原有密码修改移动到“账号安全”页签。

- 查看：按记忆编号倒序分页，每页 20 条，支持刷新和空列表提示。
- 修改：填写完整记忆内容，最多 8000 个字符，不能全为空白。保存调用现有应用服务，重新生成向量后在同一数据库事务中更新内容、向量和模型标识。
- 删除：先展示原文并确认，成功后刷新列表。删除当前页最后一条时自动返回上一页。
- 失败：保留编辑内容，展示真实接口错误，允许重试。

修改或删除长期记忆不等于清除历史任务、聊天记录或 checkpoint；已进入某次执行上下文的旧内容也不会被追溯删除。

## 后端接口

| 方法 | 路径 | 参数／结果 |
|---|---|---|
| GET | `/api/v1/user-memories` | 可选 `cursor`、`limit`，返回 `items` 与 `next_cursor` |
| PATCH | `/api/v1/user-memories/{memory_id}` | 请求体仅包含 `content`，成功返回 204 |
| DELETE | `/api/v1/user-memories/{memory_id}` | 无请求体，成功返回 204 |

三个接口都要求登录。身份来自 `CurrentPrincipal`，不由前端传入。应用服务沿用已有 `UserMemoryApplicationService`，仓储仍同时按 `tenant_id` 和 `user_id` 过滤。不存在或不属于本人的记忆统一返回 404。

前端请求通过 Next.js 的同源代理转发，复用 HttpOnly Cookie。修改、删除继续校验请求来源。没有开放创建、跨用户查询或任意后端转发能力。

## DDD 职责与修改文件

以下路径相对项目根目录：

| 文件 | 变化 |
|---|---|
| `src/agent_platform/interface/vo/user_memory_vo.py` | 新增编辑请求模型，复用领域的内容约束 |
| `src/agent_platform/interface/api/routes/v1/user_memories.py` | 新增查询、修改和删除三个入站接口，只调用应用服务 |
| `src/agent_platform/interface/api/routes/v1/__init__.py` | 注册记忆路由 |
| `frontpages/src/components/account/user-memory-manager.tsx` | 新增列表、分页、编辑、确认删除、加载与错误处理 |
| `frontpages/src/lib/user-memory-api.ts` | 新增前端记忆类型与三个 API 调用 |
| `frontpages/src/components/auth/account-settings.tsx` | 个人中心页签布局，复用 shadcn/ui Tabs 和现有密码表单 |
| `frontpages/src/components/auth/account-menu.tsx` | 入口更名为个人中心 |
| `frontpages/src/app/account/page.tsx` | 页面标题 |
| `frontpages/src/app/api/backend/[...path]/route.ts` | 增加记忆接口白名单和 DELETE 转发 |
| `frontpages/tests/auth-proxy.test.cjs` | 增加记忆转发、分页、Cookie 与删除来源校验检查 |
| `tests/unit/test_user_memory_api.py` | 新增 HTTP 参数、身份传递、未登录和结果状态契约用例 |

领域、应用服务和持久化实现直接复用现有代码，没有新增业务服务、数据库连接池或表。API 不读取数据库、不操作向量模型，不把 FastAPI Request 传入下层。

## 启用与验证

重启 FastAPI，刷新前端即可。这项功能不涉及数据库表变更，不需要执行新的 Alembic 迁移。

实际联测可按以下顺序：

1. 在任务中要求 AI 记住一条偏好，确认保存成功。
2. 打开个人中心，确认列表包含该条记忆。
3. 修改内容，刷新页面，确认显示修改后的内容。
4. 换一个账号，确认看不到上一账号的记忆。
5. 删除记录，刷新后确认不再显示。

前端 TypeScript、相关组件 lint 与 10 项代理检查通过；代理检查的上游 fetch 使用替代响应，不代表真实数据库联测。后端 HTTP 契约用例已添加，本次只执行语法和静态检查，未运行此前受外部遥测审批限制的后端联测。
