/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ShotAudioClipTypeEnum } from './ShotAudioClipTypeEnum';
/**
 * 把一个已上传音频文件绑定为镜头音频片段。
 */
export type AttachShotAudioFileRequest = {
    /**
     * 已上传的音频文件 ID
     */
    file_id: string;
    /**
     * 音频片段类型
     */
    clip_type?: ShotAudioClipTypeEnum;
    /**
     * 展示名称；为空时使用文件名
     */
    label?: (string | null);
    /**
     * 镜头内起始时间（毫秒）
     */
    start_ms?: number;
    /**
     * 镜头内结束时间；为空时暂用 0 表示待检测
     */
    end_ms?: (number | null);
    /**
     * 音量百分比
     */
    volume?: number;
    /**
     * 音轨序号
     */
    track?: number;
};

