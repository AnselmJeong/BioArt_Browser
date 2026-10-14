import type { ElectrobunConfig } from 'electrobun';

export default {
  app: { name: 'BioArt Browser', identifier: 'local.bioart.browser', version: '0.4.0' },
  build: {
    mainProcess: 'bun',
    bun: { entrypoint: 'src/bun/index.ts' },
    copy: {
      'dist/bioart-backend': 'backend',
      'build/desktop-workspace.json': 'desktop-workspace.json',
    },
    mac: { icons: 'assets/BioArt.iconset', bundleCEF: false, bundleWGPU: false, codesign: false, notarize: false, createDmg: false },
  },
  runtime: { exitOnLastWindowClosed: true },
} satisfies ElectrobunConfig;
