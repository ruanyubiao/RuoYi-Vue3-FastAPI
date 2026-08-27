/** 组装器 / 解析器 ID 与 fallback 选项（与后端 constants.py、cfg_device_connect.json 对齐）。 */

export const ASSEMBLER_PASSTHROUGH = 'passthrough'
export const ASSEMBLER_ENG_TM_SUBPKT = 'eng_tm_subpkt'
export const ASSEMBLER_CAMERA_IMAGE_D6 = 'camera_image_d6'
export const ASSEMBLER_CAN_BIU = 'can_biu'
export const ASSEMBLER_CAN_XL = 'can_xl'

export const PARSER_TM_CAN_BIU = 'tm_can_biu'
export const PARSER_TM_CAN_XL = 'tm_can_xl'
export const PARSER_CAMERA_SC_LINK41EP = 'camera_sc_link41ep'
export const PARSER_XL_BOARD_TM = 'xl_board_tm'

export const CAN_ASSEMBLER_TO_PARSER = {
  [ASSEMBLER_CAN_BIU]: PARSER_TM_CAN_BIU,
  [ASSEMBLER_CAN_XL]: PARSER_TM_CAN_XL
}

export const FALLBACK_ASSEMBLER_PASSTHROUGH = [{ id: ASSEMBLER_PASSTHROUGH, name: '透传（默认）' }]

export const FALLBACK_ASSEMBLERS_UDP = [
  { id: ASSEMBLER_PASSTHROUGH, name: '透传（默认）' },
  { id: ASSEMBLER_ENG_TM_SUBPKT, name: '工程遥测子包组装' }
]

export const FALLBACK_ASSEMBLERS_CAN = [
  { id: ASSEMBLER_PASSTHROUGH, name: '透传' },
  { id: ASSEMBLER_CAN_BIU, name: 'CAN-BIU' },
  { id: ASSEMBLER_CAN_XL, name: 'CAN-XL' }
]

export const FALLBACK_ASSEMBLERS_CAMERA = [
  { id: ASSEMBLER_PASSTHROUGH, name: '透传（默认）' },
  { id: ASSEMBLER_CAMERA_IMAGE_D6, name: '相机图像(D6)' }
]

export const FALLBACK_PARSERS_CAN = [
  { id: PARSER_TM_CAN_BIU, name: 'BIU-CAN遥测复合帧' },
  { id: PARSER_TM_CAN_XL, name: 'XL-CAN遥测复合帧' }
]

export const FALLBACK_PARSERS_CAMERA = [{ id: PARSER_CAMERA_SC_LINK41EP, name: '相机SC-LINK41EP遥测帧' }]

export const FALLBACK_PARSERS_XL_BOARD = [{ id: PARSER_XL_BOARD_TM, name: 'XL单板遥测' }]
