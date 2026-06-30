/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 角色设定图生成请求体。
 */
export type CharacterSheetTaskRequest = {
    /**
     * 可选模型 ID；不传则使用默认图片模型
     */
    model_id?: (string | null);
    /**
     * 额外参考图 file_id 列表（可不传，系统会自动注入演员/服装正面图）
     */
    images?: Array<string>;
};

