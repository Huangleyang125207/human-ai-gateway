import { registerPlugin } from '@capacitor/core';

// 真机经原生注册可直接 window.Capacitor.Plugins.NativeOcr 访问;
// 此 registerPlugin 仅为有 bundler 的消费方提供类型化入口。
export const NativeOcr = registerPlugin('NativeOcr');
