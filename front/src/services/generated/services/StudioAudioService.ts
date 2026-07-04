/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_GenerateShotTtsResponse_ } from '../models/ApiResponse_GenerateShotTtsResponse_';
import type { ApiResponse_list_ShotAudioClipRead__ } from '../models/ApiResponse_list_ShotAudioClipRead__';
import type { ApiResponse_MuxShotVideoAudioResponse_ } from '../models/ApiResponse_MuxShotVideoAudioResponse_';
import type { ApiResponse_ShotAudioClipRead_ } from '../models/ApiResponse_ShotAudioClipRead_';
import type { AttachShotAudioFileRequest } from '../models/AttachShotAudioFileRequest';
import type { GenerateShotTtsRequest } from '../models/GenerateShotTtsRequest';
import type { MuxShotVideoAudioRequest } from '../models/MuxShotVideoAudioRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioAudioService {
    /**
     * 读取镜头音频片段
     * 读取一个镜头当前已绑定的对白/BGM/音效片段。
     * @returns ApiResponse_list_ShotAudioClipRead__ Successful Response
     * @throws ApiError
     */
    public static listShotAudioClipsApiApiV1StudioAudioShotsShotIdClipsGet({
        shotId,
    }: {
        shotId: string,
    }): CancelablePromise<ApiResponse_list_ShotAudioClipRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/audio/shots/{shot_id}/clips',
            path: {
                'shot_id': shotId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 绑定已上传音频到镜头
     * 把素材库中的音频文件作为 BGM/音效/对白片段绑定到当前镜头。
     * @returns ApiResponse_ShotAudioClipRead_ Successful Response
     * @throws ApiError
     */
    public static attachShotAudioFileApiApiV1StudioAudioShotsShotIdClipsPost({
        shotId,
        requestBody,
    }: {
        shotId: string,
        requestBody: AttachShotAudioFileRequest,
    }): CancelablePromise<ApiResponse_ShotAudioClipRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/audio/shots/{shot_id}/clips',
            path: {
                'shot_id': shotId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 为镜头对白生成 TTS 配音
     * 把镜头中已确认的对白行转换为可试听、可合成的音频片段。
     * @returns ApiResponse_GenerateShotTtsResponse_ Successful Response
     * @throws ApiError
     */
    public static generateShotTtsApiApiV1StudioAudioShotsShotIdTtsPost({
        shotId,
        requestBody,
    }: {
        shotId: string,
        requestBody: GenerateShotTtsRequest,
    }): CancelablePromise<ApiResponse_GenerateShotTtsResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/audio/shots/{shot_id}/tts',
            path: {
                'shot_id': shotId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 将镜头音频合成进当前视频
     * 合成有声视频；当前环境缺 ffmpeg 时会明确提示安装依赖。
     * @returns ApiResponse_MuxShotVideoAudioResponse_ Successful Response
     * @throws ApiError
     */
    public static muxShotVideoAudioApiApiV1StudioAudioShotsShotIdMuxVideoPost({
        shotId,
        requestBody,
    }: {
        shotId: string,
        requestBody: MuxShotVideoAudioRequest,
    }): CancelablePromise<ApiResponse_MuxShotVideoAudioResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/audio/shots/{shot_id}/mux-video',
            path: {
                'shot_id': shotId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
