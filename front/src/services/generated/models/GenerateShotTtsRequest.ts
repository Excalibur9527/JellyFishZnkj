/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 为镜头对白生成 TTS 音频的请求。
 */
export type GenerateShotTtsRequest = {
    /**
     * macOS say 声音名；为空使用系统默认声音
     */
    voice?: (string | null);
    /**
     * 语速，传给 say -r；为空使用系统默认
     */
    rate?: (number | null);
    /**
     * 是否清理本镜头旧的 local_say 对白音频片段后重新生成
     */
    overwrite?: boolean;
    /**
     * 可选：仅为指定对白行生成；为空表示全部对白行
     */
    dialogue_line_ids?: (Array<number> | null);
};

