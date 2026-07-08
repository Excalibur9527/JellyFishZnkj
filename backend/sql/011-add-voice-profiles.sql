-- 011: 为演员与角色增加声线配置
-- 用途：
--   - actors.voice_profile 作为演员默认声线，供角色继承；
--   - characters.voice_profile 作为角色专属声线，优先级高于演员；
--   - 当前本地 TTS 使用 local_say 配置，后续云 TTS 可在同一 JSON 中追加供应商 voice id。
ALTER TABLE actors
    ADD COLUMN voice_profile JSON NOT NULL DEFAULT '{}' COMMENT '演员声线配置：按 TTS 供应商保存音色 ID、语速等参数，供角色对白配音继承';

ALTER TABLE characters
    ADD COLUMN voice_profile JSON NOT NULL DEFAULT '{}' COMMENT '角色声线配置：优先级高于关联演员，用于同一角色跨镜头保持声音一致';
