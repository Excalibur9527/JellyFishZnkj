/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ShotFrameType } from './ShotFrameType';
import type { ShotLinkedAssetItem } from './ShotLinkedAssetItem';
export type ShotFrameImageCreate = {
    shot_detail_id: string;
    frame_type: ShotFrameType;
    file_id?: (string | null);
    width?: (number | null);
    height?: (number | null);
    format?: string;
    reference_assets?: Array<ShotLinkedAssetItem>;
};

