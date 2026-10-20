import { describe, expect, it } from 'vitest'
import { markIconButtons } from '@/utils/buttonLoading'

function button(html) {
  const host = document.createElement('div')
  host.innerHTML = html
  return host
}

describe('markIconButtons', () => {
  it('给带图标的按钮打标，纯文字和 loading 图标不打标', () => {
    const host = button(`
      <button class="el-button"><i class="el-icon"></i><span>上传</span></button>
      <button class="el-button"><span>保存</span></button>
      <button class="el-button is-loading"><i class="el-icon is-loading"></i><span>保存</span></button>
    `)
    markIconButtons(host)
    const [iconBtn, textBtn, loadingBtn] = host.querySelectorAll('.el-button')
    expect(iconBtn.dataset.hasIcon).toBe('1')
    expect(textBtn.dataset.hasIcon).toBeUndefined()
    expect(loadingBtn.dataset.hasIcon).toBeUndefined()
  })

  it('已经打标的按钮在只剩转圈时仍保留标记', () => {
    const host = button(`<button class="el-button"><i class="el-icon"></i><span>上传</span></button>`)
    markIconButtons(host)
    const btn = host.querySelector('.el-button')
    btn.classList.add('is-loading')
    btn.querySelector('.el-icon').classList.add('is-loading')
    markIconButtons(host)
    expect(btn.dataset.hasIcon).toBe('1')
  })
})