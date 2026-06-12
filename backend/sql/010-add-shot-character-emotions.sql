-- 010: 给 shots 表添加 character_emotions 字段，用于存储分镜时推断的角色情绪与微表情
ALTER TABLE shots
    ADD COLUMN character_emotions JSON NULL COMMENT '分镜时推断的各角色情绪与微表情，格式：[{character_name, emotion, intensity, expression_hint}]'
    AFTER script_excerpt;
