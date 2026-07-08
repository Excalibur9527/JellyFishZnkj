-- 009: 为 characters 表新增 visual_fingerprint 字段
-- 用途：存储 AI 优化后的角色视觉标签（面部特征/体型/服装颜色等）
--       供分镜帧提示词生成时直接复用，提升跨镜头角色外貌一致性
ALTER TABLE characters
    ADD COLUMN visual_fingerprint TEXT NOT NULL DEFAULT '' COMMENT '角色视觉指纹：AI 优化后的可生成外貌描述，用于稳定跨镜头角色外貌';
