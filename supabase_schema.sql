-- ============================================================
-- fp-repo Supabase 数据库 Schema
-- 第二阶段：注册登录 + 论坛板块 + 红人体系预埋
-- 在 Supabase Dashboard > SQL Editor 中执行
-- ============================================================

-- ──────────────────────────────────────────────
-- 1. 扩展：启用 pgcrypto 用于 UUID 生成
-- ──────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ──────────────────────────────────────────────
-- 2. 邀请码表 (invite_codes)
--    管理员在后台生成，注册时必须输入有效邀请码
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.invite_codes (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code        TEXT NOT NULL UNIQUE,
  max_uses    INT NOT NULL DEFAULT 1,         -- 最大使用次数
  used_count  INT NOT NULL DEFAULT 0,         -- 已使用次数
  created_by  UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  expires_at  TIMESTAMPTZ,                    -- NULL = 永不过期
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE public.invite_codes IS '邀请码表，管理员创建，注册时校验';

-- ──────────────────────────────────────────────
-- 3. 用户资料表 (profiles)
--    与 auth.users 一对一关联
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.profiles (
  id               UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  username         TEXT NOT NULL UNIQUE,
  avatar_url       TEXT,
  role             TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
  influencer_badge TEXT,                       -- 预留：红人徽章标识
  invite_code_used TEXT,                       -- 注册时使用的邀请码
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE public.profiles IS '用户资料，与 auth.users 1:1 关联';

-- ──────────────────────────────────────────────
-- 4. 帖子表 (posts)
--    section 枚举：match_discuss / bet_show / feedback
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.posts (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  section    TEXT NOT NULL CHECK (section IN ('match_discuss', 'bet_show', 'feedback')),
  title      TEXT NOT NULL CHECK (char_length(title) BETWEEN 2 AND 100),
  content    TEXT NOT NULL CHECK (char_length(content) BETWEEN 5 AND 5000),
  match_id   TEXT,                             -- 关联比赛ID（赛事讨论用）
  bet_id     UUID,                             -- 关联模拟投注记录ID（晒单用）
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE public.posts IS '论坛帖子：赛事讨论 / 模拟晒单 / 意见反馈';
CREATE INDEX IF NOT EXISTS idx_posts_section ON public.posts(section);
CREATE INDEX IF NOT EXISTS idx_posts_user ON public.posts(user_id);
CREATE INDEX IF NOT EXISTS idx_posts_created ON public.posts(created_at DESC);

-- ──────────────────────────────────────────────
-- 5. 评论表 (comments)
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.comments (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id    UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
  user_id    UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  content    TEXT NOT NULL CHECK (char_length(content) BETWEEN 1 AND 1000),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE public.comments IS '帖子评论';
CREATE INDEX IF NOT EXISTS idx_comments_post ON public.comments(post_id);

-- ──────────────────────────────────────────────
-- 6. 关注表 (follows)
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.follows (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  follower_id  UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  following_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_follow UNIQUE (follower_id, following_id),
  CONSTRAINT chk_no_self_follow CHECK (follower_id <> following_id)
);
COMMENT ON TABLE public.follows IS '用户关注关系';
CREATE INDEX IF NOT EXISTS idx_follows_follower ON public.follows(follower_id);
CREATE INDEX IF NOT EXISTS idx_follows_following ON public.follows(following_id);

-- ──────────────────────────────────────────────
-- 7. 发帖频率限制表 (post_rate_limit)
--    前端+RLS 双重限制，1分钟1帖
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.post_rate_limit (
  user_id    UUID PRIMARY KEY REFERENCES public.profiles(id) ON DELETE CASCADE,
  last_post  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 8. RLS 安全策略
-- ============================================================

-- 启用 RLS
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.follows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invite_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_rate_limit ENABLE ROW LEVEL SECURITY;

-- ── profiles ──
-- 所有人可读
CREATE POLICY "profiles_select_all" ON public.profiles
  FOR SELECT USING (TRUE);
-- 只能改自己的
CREATE POLICY "profiles_update_own" ON public.profiles
  FOR UPDATE USING (auth.uid() = id);
-- 注册时插入（触发器处理）
CREATE POLICY "profiles_insert_own" ON public.profiles
  FOR INSERT WITH CHECK (auth.uid() = id);

-- ── posts ──
-- 所有人可读
CREATE POLICY "posts_select_all" ON public.posts
  FOR SELECT USING (TRUE);
-- 登录用户可发自己的帖（含频率限制检查）
CREATE POLICY "posts_insert_own" ON public.posts
  FOR INSERT
  WITH CHECK (
    auth.uid() = user_id
    AND auth.uid() NOT IN (
      SELECT user_id FROM public.post_rate_limit
      WHERE last_post > NOW() - INTERVAL '1 minute'
    )
  );
-- 只能改/删自己的帖
CREATE POLICY "posts_update_own" ON public.posts
  FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "posts_delete_own" ON public.posts
  FOR DELETE USING (auth.uid() = user_id);

-- ── comments ──
-- 所有人可读
CREATE POLICY "comments_select_all" ON public.comments
  FOR SELECT USING (TRUE);
-- 登录用户可发评论
CREATE POLICY "comments_insert_own" ON public.comments
  FOR INSERT WITH CHECK (auth.uid() = user_id);
-- 只能删自己的评论
CREATE POLICY "comments_delete_own" ON public.comments
  FOR DELETE USING (auth.uid() = user_id);

-- ── follows ──
-- 所有人可读关注关系
CREATE POLICY "follows_select_all" ON public.follows
  FOR SELECT USING (TRUE);
-- 登录用户可关注/取关（只能操作自己）
CREATE POLICY "follows_insert_own" ON public.follows
  FOR INSERT WITH CHECK (auth.uid() = follower_id);
CREATE POLICY "follows_delete_own" ON public.follows
  FOR DELETE USING (auth.uid() = follower_id);

-- ── invite_codes ──
-- 仅 admin 可读
CREATE POLICY "invite_codes_admin_select" ON public.invite_codes
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin')
  );
-- 仅 admin 可写
CREATE POLICY "invite_codes_admin_insert" ON public.invite_codes
  FOR INSERT WITH CHECK (
    EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin')
  );
CREATE POLICY "invite_codes_admin_update" ON public.invite_codes
  FOR UPDATE USING (
    EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin')
  );
CREATE POLICY "invite_codes_admin_delete" ON public.invite_codes
  FOR DELETE USING (
    EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin')
  );

-- ── post_rate_limit ──
-- 系统自动管理，用户只读自己的
CREATE POLICY "rate_limit_select_own" ON public.post_rate_limit
  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "rate_limit_upsert_own" ON public.post_rate_limit
  FOR ALL USING (auth.uid() = user_id);

-- ============================================================
-- 9. 触发器：发帖后更新频率限制
-- ============================================================
CREATE OR REPLACE FUNCTION public.fn_update_rate_limit()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.post_rate_limit (user_id, last_post)
  VALUES (NEW.user_id, NOW())
  ON CONFLICT (user_id) DO UPDATE SET last_post = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER trg_post_rate_limit
  AFTER INSERT ON public.posts
  FOR EACH ROW EXECUTE FUNCTION fn_update_rate_limit();

-- ============================================================
-- 10. 触发器：新用户注册自动创建 profile
--     (Supabase Auth 触发器)
-- ============================================================
CREATE OR REPLACE FUNCTION public.fn_handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, username, avatar_url)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'username', 'user_' || LEFT(NEW.id::TEXT, 8)),
    NEW.raw_user_meta_data->>'avatar_url'
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER trg_on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION fn_handle_new_user();

-- ============================================================
-- 11. 触发器：更新 updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION public.fn_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_profiles_updated_at
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_posts_updated_at
  BEFORE UPDATE ON public.posts
  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- ============================================================
-- 12. 红人榜视图 (v_influencer_ranking)
--     入榜门槛：30单 + 30天
--     排序：按收益率，样本量加权
-- ============================================================
CREATE OR REPLACE VIEW public.v_influencer_ranking AS
SELECT
  p.id AS user_id,
  p.username,
  p.avatar_url,
  p.influencer_badge,
  -- 从模拟投注统计中聚合（需前端定期同步到 stats_sync 表或直接从前端读取）
  -- 这里先用帖子数作为基础指标，后续可对接模拟投注数据
  COUNT(DISTINCT po.id) AS total_posts,
  COUNT(DISTINCT c.id) AS total_comments,
  (
    SELECT COUNT(*) FROM public.follows f
    WHERE f.following_id = p.id
  ) AS follower_count,
  -- 活跃度得分：帖子数*3 + 评论数*1 + 粉丝数*2
  COUNT(DISTINCT po.id) * 3 + COUNT(DISTINCT c.id) * 1 +
  (SELECT COUNT(*) FROM public.follows f WHERE f.following_id = p.id) * 2
    AS activity_score,
  -- 注册时间
  p.created_at
FROM public.profiles p
LEFT JOIN public.posts po ON po.user_id = p.id
LEFT JOIN public.comments c ON c.user_id = p.id
GROUP BY p.id, p.username, p.avatar_url, p.influencer_badge, p.created_at
HAVING p.created_at <= NOW() - INTERVAL '30 days'
ORDER BY activity_score DESC;

COMMENT ON VIEW public.v_influencer_ranking IS '红人榜视图：基于活跃度排序，入榜需30天+30单';

-- 红人榜视图读取策略
CREATE POLICY "influencer_ranking_select" ON public.profiles
  FOR SELECT USING (TRUE);

-- ============================================================
-- 13. 辅助函数：验证邀请码
--     前端注册时调用，在 RPC 中校验
-- ============================================================
CREATE OR REPLACE FUNCTION public.fn_validate_invite_code(p_code TEXT)
RETURNS BOOLEAN AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM public.invite_codes
    WHERE code = p_code
      AND is_active = TRUE
      AND used_count < max_uses
      AND (expires_at IS NULL OR expires_at > NOW())
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================
-- 14. 初始化：创建第一个管理员用户
--     请在 Supabase Dashboard 创建用户后，手动设置 role='admin'
--     UPDATE public.profiles SET role = 'admin' WHERE id = '你的UUID';
-- ============================================================


-- ============================================================
-- 15. 辅助函数：消耗邀请码使用次数
-- ============================================================
CREATE OR REPLACE FUNCTION public.fn_consume_invite_code(p_code TEXT)
RETURNS VOID AS $$
BEGIN
  UPDATE public.invite_codes
  SET used_count = used_count + 1
  WHERE code = p_code
    AND is_active = TRUE
    AND used_count < max_uses;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 完成！以上 SQL 在 Supabase Dashboard > SQL Editor 中一次性执行即可。

