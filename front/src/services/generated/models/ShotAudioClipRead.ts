/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { FileRead } from './FileRead';
import type { ShotAudioClipTypeEnum } from './ShotAudioClipTypeEnum';
/**
 * 镜头音频片段读取模型。
 */
export type ShotAudioClipRead = {
    id: number;
    shot_id: string;
    file_id: string;
    dialogue_line_id: (number | null);
    clip_type: ShotAudioClipTypeEnum;
    label: string;
    start_ms: number;
    end_ms: number;
    volume: number;
    track: number;
    provider: string;
    voice: string;
    usage_kind: string;
    /**
     * 关联音频文件
     */
    file?: (FileRead | null);
};

