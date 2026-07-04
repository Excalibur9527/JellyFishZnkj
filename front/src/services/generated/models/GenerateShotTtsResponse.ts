/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ShotAudioClipRead } from './ShotAudioClipRead';
/**
 * 镜头 TTS 生成结果。
 */
export type GenerateShotTtsResponse = {
    /**
     * 本次生成的音频片段
     */
    clips?: Array<ShotAudioClipRead>;
    /**
     * 结果说明
     */
    message?: string;
};

