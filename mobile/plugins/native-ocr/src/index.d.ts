export interface NativeOcrPlugin {
  /** 当前设备/系统是否支持端侧 OCR(iOS 13+ Vision / Android MLKit 已 ready) */
  available(): Promise<{ available: boolean; engine: string; reason?: string }>;
  /**
   * 端侧识别图中文字。
   *
   * @param options.image  dataURL(`data:image/jpeg;base64,...`)或裸 base64
   * @param options.languages  识别语言提示(iOS 16+ 中文走 zh-Hans;Android MLKit 走 ChineseTextRecognizerOptions)
   *
   * @returns text     按行 join 的全部识别文字
   *          blocks   细粒度行/块,带 bbox + confidence(用户场景一般不需要,留扩展)
   *          engine   实际跑的引擎名("VNRecognizeText" / "MLKitTextRecognition" / "PaddleOCR")
   */
  recognize(options: {
    image: string;
    languages?: string[];
  }): Promise<{
    text: string;
    blocks: Array<{ text: string; confidence?: number; bbox?: { x: number; y: number; w: number; h: number } }>;
    engine: string;
  }>;
}

export const NativeOcr: NativeOcrPlugin;
