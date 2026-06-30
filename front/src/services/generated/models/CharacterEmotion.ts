/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 单镜中单个角色的情绪与微表情推断。
 */
export type CharacterEmotion = {
    /**
     * 角色名
     */
    character_name: string;
    /**
     * 主情绪标签，如：悲伤、愤怒、惊恐、喜悦、平静、紧张、羞耻、绝望
     */
    emotion?: string;
    /**
     * 情绪强度：轻微 / 明显 / 强烈
     */
    intensity?: string;
    /**
     * 具体微表情描述，如：眉头紧皱、眼眶泛红、嘴唇微颤、目光涣散
     */
    expression_hint?: string;
};

