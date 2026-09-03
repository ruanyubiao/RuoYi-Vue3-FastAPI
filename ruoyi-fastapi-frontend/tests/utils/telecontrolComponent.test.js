import { describe, expect, it } from 'vitest'
import {
  coerceSavedCompValue,
  componentLabel,
  componentTip,
  hasFormula,
  orderTip,
  isFloatUi,
  isIntegerDataType,
  numBound,
  numberPrecision,
  numberStep,
  resolveCompValuesForOrder,
  resolveComponentValue,
  uiDataType
} from '@/utils/telecontrolComponent'

describe('utils/telecontrolComponent', () => {
  it('uiDataType 优先 dataTypeUI', () => {
    expect(uiDataType({ dataTypeUI: 'float', dataType: 'INT16' })).toBe('FLOAT')
    expect(uiDataType({ dataType: 'int32' })).toBe('INT32')
    expect(uiDataType({})).toBe('INT16')
  })

  it('浮点/整数精度与步进', () => {
    const floatComp = { dataTypeUI: 'DOUBLE' }
    expect(isFloatUi(floatComp)).toBe(true)
    expect(numberPrecision(floatComp)).toBe(6)
    expect(numberStep(floatComp)).toBe(0.1)
    expect(isIntegerDataType('INT16')).toBe(true)
    expect(isIntegerDataType('FLOAT')).toBe(false)
    expect(numberStep({ dataType: 'UINT16' })).toBe(1)
    expect(numberStep({ dataType: 'UINT16', stepVal: '4' })).toBe(4)
    expect(numberStep({ dataTypeUI: 'FLOAT', stepVal: '0.25' })).toBe(0.25)
    expect(numberStep({ dataType: 'INT16', stepVal: '' })).toBe(1)
    expect(numberStep({ dataType: 'INT16', stepVal: '0' })).toBe(1)
    expect(numberStep({ dataType: 'INT16', stepVal: '-2' })).toBe(1)
  })

  it('numBound 空值不限制', () => {
    expect(numBound('')).toBeUndefined()
    expect(numBound(null)).toBeUndefined()
    expect(numBound('12')).toBe(12)
    expect(numBound('x')).toBeUndefined()
  })

  it('resolveComponentValue 按控件类型', () => {
    expect(resolveComponentValue({ componentType: 'number', dataType: 'INT16', defaultVal: '3.9' })).toBe(3)
    expect(resolveComponentValue({ componentType: 'select', options: { a: 'A', b: 'B' }, defaultVal: 'z' })).toBe('a')
    expect(resolveComponentValue({ componentType: 'scientific', defaultVal: '' })).toBe('0')
    expect(resolveComponentValue({ componentType: 'text', defaultVal: 'x' })).toBe('x')
  })

  it('coerceSavedCompValue select 可按 label 匹配', () => {
    const comp = { componentType: 'select', options: { on: '开', off: '关' }, defaultVal: 'off' }
    expect(coerceSavedCompValue(comp, '开')).toBe('on')
    expect(coerceSavedCompValue(comp, 'unknown')).toBe('off')
  })

  it('coerceSavedCompValue number 钳制 min/max', () => {
    const comp = { componentType: 'number', dataType: 'INT16', defaultVal: 5, minVal: '1', maxVal: '10' }
    expect(coerceSavedCompValue(comp, 0)).toBe(1)
    expect(coerceSavedCompValue(comp, 99)).toBe(10)
    expect(coerceSavedCompValue(comp, 7)).toBe(7)
  })

  it('resolveCompValuesForOrder 对齐 component 长度', () => {
    const order = {
      component: [
        { componentType: 'number', dataType: 'INT16', defaultVal: 1 },
        { componentType: 'fixed', defaultVal: 'x' }
      ]
    }
    expect(resolveCompValuesForOrder(order, [3])).toEqual([3, 'x'])
  })

  it('hasFormula 识别非空公式', () => {
    expect(hasFormula({ formula: ' x+1 ' })).toBe(true)
    expect(hasFormula({ formula: '' })).toBe(false)
  })

  it('componentLabel / componentTip', () => {
    expect(componentLabel({ title: '调制比' }, 2)).toBe('调制比')
    expect(componentLabel({ name: '备用名' }, 0)).toBe('备用名')
    expect(componentLabel({}, 1)).toBe('参数2')
    expect(componentTip({ tip: '  取值范围  ' })).toBe('取值范围')
    expect(componentTip({})).toBe('')
    expect(orderTip({ tip: ' 指令说明 ' })).toBe('指令说明')
    expect(orderTip({})).toBe('')
  })
})
