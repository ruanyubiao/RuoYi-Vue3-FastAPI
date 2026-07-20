<template>
  <section class="app-main">
    <router-view v-slot="{ Component, route }">
      <transition name="fade-transform" mode="out-in">
        <keep-alive :include="cachedViews">
          <component v-if="!route.meta.link" :is="Component" :key="route.name || route.path"/>
        </keep-alive>
      </transition>
    </router-view>
    <iframe-toggle />
    <copyright />
  </section>
</template>

<script setup>
import { storeToRefs } from 'pinia'
import copyright from "./Copyright/index"
import iframeToggle from "./IframeToggle/index"
import useTagsViewStore from '@/store/modules/tagsView'

const route = useRoute()
const tagsViewStore = useTagsViewStore()
const { cachedViews } = storeToRefs(tagsViewStore)

onMounted(() => {
  addIframe()
})

watchEffect(() => {
  addIframe()
})

function addIframe() {
  if (route.meta.link) {
    useTagsViewStore().addIframeView(route)
  }
}
</script>

<style lang="scss" scoped>
.app-main {
  /* 50 = navbar */
  --app-main-offset: 50px;
  /* 36 = fixed copyright footer */
  --app-footer-offset: 0px;
  min-height: calc(100vh - var(--app-main-offset) - var(--app-footer-offset));
  width: 100%;
  position: relative;
  overflow: hidden;
}

.fixed-header + .app-main {
  overflow-y: auto;
  scrollbar-gutter: auto;
  height: calc(100vh - var(--app-main-offset) - var(--app-footer-offset));
  min-height: 0px;
  margin-top: 50px;
}

/* footer 为 fixed，从主区域高度中扣掉，避免内容区再垫 padding 导致双滚动条 */
.app-main:has(.copyright) {
  --app-footer-offset: 36px;
}

.hasTagsView {
  .app-main {
    /* 84 = navbar + tags-view = 50 + 34 */
    --app-main-offset: 84px;
    min-height: calc(100vh - var(--app-main-offset) - var(--app-footer-offset));
  }

  .fixed-header + .app-main {
    margin-top: 84px;
    height: calc(100vh - var(--app-main-offset) - var(--app-footer-offset));
    min-height: 0px;
  }
}

/* 移动端fixed-header优化 */
@media screen and (max-width: 991px) {
  .fixed-header + .app-main {
    padding-bottom: max(60px, calc(constant(safe-area-inset-bottom) + 40px));
    padding-bottom: max(60px, calc(env(safe-area-inset-bottom) + 40px));
    overscroll-behavior-y: none;
  }

  .hasTagsView .fixed-header + .app-main {
    padding-bottom: max(60px, calc(constant(safe-area-inset-bottom) + 40px));
    padding-bottom: max(60px, calc(env(safe-area-inset-bottom) + 40px));
    overscroll-behavior-y: none;
  }

  /* 移动端额外 bottom padding 时不再叠加 footer offset，避免高度算重 */
  .fixed-header + .app-main:has(.copyright) {
    --app-footer-offset: 0px;
  }
}

@supports (-webkit-touch-callout: none) {
  @media screen and (max-width: 991px) {
    .fixed-header + .app-main {
      padding-bottom: max(17px, calc(constant(safe-area-inset-bottom) + 10px));
      padding-bottom: max(17px, calc(env(safe-area-inset-bottom) + 10px));
      height: calc(100svh - var(--app-main-offset) - var(--app-footer-offset));
      height: calc(100dvh - var(--app-main-offset) - var(--app-footer-offset));
    }

    .hasTagsView .fixed-header + .app-main {
      padding-bottom: max(17px, calc(constant(safe-area-inset-bottom) + 10px));
      padding-bottom: max(17px, calc(env(safe-area-inset-bottom) + 10px));
      height: calc(100svh - var(--app-main-offset) - var(--app-footer-offset));
      height: calc(100dvh - var(--app-main-offset) - var(--app-footer-offset));
    }
  }
}
</style>

<style lang="scss">
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background-color: #f1f1f1;
}

::-webkit-scrollbar-thumb {
  background-color: #c0c0c0;
  border-radius: 3px;
}
</style>

