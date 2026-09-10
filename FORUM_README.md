# fp-repo 第二阶段：社区论坛 + 注册登录 + 红人体系

## 功能概览

| 模块 | 说明 | 状态 |
|------|------|------|
| 注册登录 | Supabase Auth + 邀请码制 | ✅ 完成 |
| 赛事讨论 | 围绕比赛的帖子，可关联比赛ID | ✅ 完成 |
| 模拟晒单 | 从模拟投注记录一键生成帖子 | ✅ 完成 |
| 意见反馈 | 网站建议反馈 | ✅ 完成 |
| 红人榜 | 基于战绩+活跃度的排名视图 | ✅ 预埋（前端占位） |

## 部署步骤

### 1. 创建 Supabase 项目
1. 访问 https://supabase.com 注册并创建项目
2. 记录 **Project URL** 和 **anon public key**（Settings > API）
3. **⚠️ service_role key 绝不放前端！**

### 2. 执行数据库 Schema
1. 进入 Supabase Dashboard > SQL Editor
2. 复制 `supabase_schema.sql` 全部内容粘贴执行
3. 确认所有表和策略创建成功

### 3. 配置前端
1. 打开 `supabase_config.js`
2. 替换以下两个值：
   ```js
   var SUPABASE_URL = 'https://xxx.supabase.co';
   var SUPABASE_ANON_KEY = 'eyJhbG...';
   ```
3. 提交代码到 GitHub

### 4. 创建管理员账号
1. 在 Supabase Dashboard > Authentication 手动创建一个用户
2. 在 SQL Editor 执行：
   ```sql
   UPDATE public.profiles SET role = 'admin' WHERE email = '你的邮箱';
   ```

### 5. 生成邀请码
在 SQL Editor 执行：
```sql
INSERT INTO public.invite_codes (code, max_uses, created_by)
VALUES ('FP2026', 100, '管理员UUID');
```

### 6. 配置 Supabase Auth
1. Dashboard > Authentication > Providers > Email
2. 开启 Email provider
3. 关闭 "Confirm email"（初期简化流程）或开启（更安全）
4. 设置 Site URL 为你的 GitHub Pages 地址

## 文件清单

| 文件 | 说明 |
|------|------|
| `supabase_schema.sql` | 数据库建表 + RLS策略 + 触发器 + 红人视图 |
| `supabase_config.js` | Supabase 初始化配置（需替换URL和Key） |
| `auth.js` | 登录/注册弹窗 + 邀请码校验 + 用户状态管理 |
| `forum.js` | 论坛三板块：发帖/评论/晒单 + 敏感词过滤 |
| `index.html` | 新增登录入口 + 论坛Tab + 红人榜Tab |

## 安全设计

### RLS 策略
- **posts/comments**: 所有人可读，登录用户只能写自己的
- **profiles**: 所有人可读，用户只能改自己的
- **follows**: 所有人可读，登录用户可关注/取关
- **invite_codes**: 仅 admin 可读写
- **发帖频率**: 1分钟1帖（前端 + RLS 双重限制）

### 敏感词过滤
- 前端 JS 常量列表，发帖/评论/用户名均检查
- 包含敏感词时阻止提交并提示

### 合规
- 页面标注"模拟投注仅供策略验证，不构成投注建议"
- service_role key 绝不放前端
- 仅使用 anon key

## 红人榜视图逻辑

```sql
-- 入榜门槛：注册满30天
-- 排序：活跃度得分 = 帖子数*3 + 评论数*1 + 粉丝数*2
-- 预留：后续对接模拟投注战绩数据（收益率+胜率加权）
```

## 后续迭代计划

- [ ] 红人榜前端展示（对接 v_influencer_ranking 视图）
- [ ] 模拟投注数据同步到 Supabase（stats_sync 表）
- [ ] 帖子图片上传（Supabase Storage）
- [ ] 关注/取关前端交互
- [ ] 帖子点赞功能
- [ ] 管理员后台（邀请码管理、内容审核）

## 注意事项

- GitHub Pages 是静态部署，所有数据交互通过 Supabase JS SDK
- 无需自建后端服务器
- Supabase 免费层限制：500MB 数据库、1GB 存储、50000 月活用户
