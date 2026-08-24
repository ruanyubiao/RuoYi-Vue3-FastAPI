"""相机图像索引：应答为 0 时回退到请求序号。"""

from module_payload.collectors.plugins.camera_image import CameraImageSerialPlugin


def test_effective_image_no_falls_back_when_device_echoes_zero() -> None:
    p = CameraImageSerialPlugin()
    p._cfg['image_no'] = 7
    assert p._effective_image_no(0) == 7
    assert p._effective_image_no(None) == 7
    assert p._effective_image_no(3) == 3


def test_apply_cfg_accepts_camel_image_no() -> None:
    p = CameraImageSerialPlugin()
    p._apply_cfg({'imageNo': 12})
    assert p._requested_image_no() == 12
    p._apply_cfg({'image_no': 4})
    assert p._requested_image_no() == 4
