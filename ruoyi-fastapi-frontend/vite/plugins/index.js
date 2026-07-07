import vue from '@vitejs/plugin-vue'

import createAutoImport from './auto-import'
import createSvgIcon from './svg-icon'
import createCompression from './compression'
import createSetupExtend from './setup-extend'
import vueDevTools from 'vite-plugin-vue-devtools'

export default function createVitePlugins(viteEnv, isBuild = false) {
    const vitePlugins = [vue()]
    !isBuild && vitePlugins.push(vueDevTools())
    vitePlugins.push(createAutoImport())
	vitePlugins.push(createSetupExtend())
    vitePlugins.push(createSvgIcon(isBuild))
	isBuild && vitePlugins.push(...createCompression(viteEnv))
    return vitePlugins
}
