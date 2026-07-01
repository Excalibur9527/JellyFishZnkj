/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ShotFrameType } from './ShotFrameType';
import type { ShotLinkedAssetItem } from './ShotLinkedAssetItem';
export type ShotFrameImageUpdate = {
    frame_type?: (ShotFrameType | null);
    file_id?: (string | null);
    width?: (number | null);
    height?: (number | null);
    format?: (string | null);
    reference_assets?: (Array<ShotLinkedAssetItem> | null);
};

