export interface CutoutPlugin {
  /** 当前设备/系统是否支持端侧抠图(iOS 17+ / Android ML Kit) */
  available(): Promise<{ available: boolean; reason?: string }>;
  /** 抠出主体,返回透明背景 PNG 的 data url */
  cutout(options: { image: string }): Promise<{ png: string }>;
}

export const Cutout: CutoutPlugin;
