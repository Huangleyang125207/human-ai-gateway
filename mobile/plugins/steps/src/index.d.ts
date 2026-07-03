export type CapState = 'granted' | 'denied' | 'undetermined' | 'unavailable';

export interface StepsPlugin {
  /** 查当前授权状态,不弹框 */
  probe(): Promise<{ state: CapState }>;
  /** 触发系统授权框(iOS「运动与健身」/ Android「身体活动」),返最终状态 */
  request(): Promise<{ state: CapState }>;
  /** 当日步数。iOS 精确(CMPedometer 按自然日查询);Android 传感器基线近似(approximate=true 表示首日/重启后从当下起算) */
  today(): Promise<{ steps: number; since: string; source: 'coremotion' | 'sensor'; approximate: boolean }>;
}

export declare const Steps: StepsPlugin;
