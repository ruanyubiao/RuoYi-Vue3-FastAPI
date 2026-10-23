# -*- coding: utf-8 -*-
"""XL camera image-serial HIL (v1.6 / v1.7).

Required UI capture path:
  1) uncheck auto-capture
  2) click image-refresh

Acceptance (asserted):
  A) page-parsed display (resolution etc.) matches sent image params
  B) image payload matches: line TX pixels == IPC RX == page canvas
"""
from __future__ import annotations

import base64
import io
import time

import numpy as np
import pytest
from PIL import Image

from conftest import require_serial
from hil.config import CONFIG
from hil.hw.camera_image_d6 import DATA_CHUNK, make_test_image, resolution_label
from hil.hw.camera_image_sim import CameraImageSim

pytestmark = [pytest.mark.hil_serial, pytest.mark.asyncio(loop_scope="session")]

_BOARDS = [
    ("camera", "v16", "xl-camera-image", "/xl/board/camera"),
    ("camera-v17", "v17", "xl-camera-v17-image", "/xl/board/camera_v17"),
]


def _cases():
    out = []
    for board, proto, key, path in _BOARDS:
        # 400 and another 8-multiple < 400
        sides = [256, 400] if board == "camera" else [320, 400]
        for side in sides:
            out.append((board, proto, key, path, side))
    return out


def _case_id(c):
    board, _proto, _key, _path, side = c
    ver = "v16" if board == "camera" else "v17"
    return f"{ver}_{side}"


def _png_to_gray(b64: str) -> np.ndarray:
    raw = base64.b64decode(b64)
    im = Image.open(io.BytesIO(raw))
    if im.mode != "L":
        im = im.convert("L")
    return np.asarray(im, dtype=np.uint8)


def _expected_chunks(side: int) -> int:
    total = side * side
    full, rem = divmod(total, DATA_CHUNK)
    return full + (1 if rem else 0)


@pytest.mark.parametrize("case", _cases(), ids=_case_id)
async def test_camera_image_xfer(ui, api, case):
    board, proto, image_key, page_path, side = case
    ctrl_key = "xl-camera" if board == "camera" else "xl-camera-v17"
    port, ipc_port = require_serial(ctrl_key)
    if not port or not ipc_port:
        pytest.skip("serial ports not configured (need COM9 <-> COM11)")

    busy = api.busy_serial(ipc_port)
    if busy:
        pytest.fail(f"IPC serial {ipc_port} busy: {busy}")

    pixels = make_test_image(side, seed=42)
    res_label = resolution_label(side, board)
    expect_res_text = f"{side}\u00d7{side}"
    sim = CameraImageSim(port, protocol=proto, baudrate=2_000_000, pixels=pixels, parity="O")
    try:
        api.ensure_hardware_idle(reason=f"before camera image {board} {side}", timeout_s=12.0)
        sim.start()
        time.sleep(0.5)

        page = await ui.goto(page_path, settle_ms=1000)
        from hil.browser.pages import (
            camera_open_image_serial,
            camera_set_resolution,
            camera_uncheck_auto_capture,
            camera_click_refresh_once,
            camera_wait_displayed_resolution,
            camera_canvas_gray_array,
            serial_ui_close,
        )

        try:
            await camera_open_image_serial(page, ipc_port)
            await camera_set_resolution(page, side, board=board)

            # Required UI path: cancel auto-capture, then image-refresh
            await camera_uncheck_auto_capture(page)

            got_img = None
            last_phase = ""
            last_meta = {}
            n_expect = _expected_chunks(side)
            # one automatic retry: cold-start 400px transfers can stall mid-frame
            for attempt in range(2):
                before = api.get_camera_image(ipc_port, since="") or {}
                since = str(((before.get("image") or {}).get("path") or ""))
                sim.rx_requests.clear()
                sim.tx_responses.clear()
                await camera_click_refresh_once(page)

                deadline = time.time() + (120.0 if side >= 400 else 60.0)
                got_img = None
                last_phase = ""
                last_meta = {}
                while time.time() < deadline:
                    data = api.get_camera_image(ipc_port, since=since) or {}
                    img = data.get("image") or {}
                    st = data.get("status") or {}
                    meta = img.get("meta") or {}
                    last_meta = meta
                    phase = str(
                        meta.get("phase") or st.get("imagePhase") or st.get("phase") or ""
                    ).lower()
                    last_phase = phase
                    msg = str(
                        meta.get("message") or meta.get("tip") or st.get("message") or ""
                    )
                    if phase == "failed":
                        print(
                            f"[HIL] image failed attempt={attempt} msg={msg!r} "
                            f"tx={len(sim.tx_responses)}/{n_expect}",
                            flush=True,
                        )
                        break
                    if img.get("data") and (
                        img.get("changed") or str(img.get("path") or "") != since
                    ):
                        got_img = img
                        break
                    if phase == "ready" and img.get("data"):
                        got_img = img
                        break
                    if len(sim.tx_responses) >= n_expect and len(sim.rx_requests) >= n_expect:
                        time.sleep(0.3)
                        continue
                    time.sleep(0.2)

                if got_img is not None:
                    break
                try:
                    api.stop_camera(ipc_port)
                except Exception:
                    pass
                time.sleep(0.8)
                print(
                    f"[HIL] retry image refresh board={board} side={side} "
                    f"attempt={attempt} tx={len(sim.tx_responses)}/{n_expect} "
                    f"phase={last_phase!r}",
                    flush=True,
                )

            assert len(sim.rx_requests) >= 1, (
                f"PC did not RX any D6 request after UI refresh; res={res_label} errors={sim.errors[-3:]}"
            )
            assert got_img is not None, (
                f"IPC did not publish image after UI refresh; phase={last_phase!r} meta={last_meta} "
                f"tx={len(sim.tx_responses)}/{n_expect} rx={len(sim.rx_requests)} "
                f"res={res_label} errors={sim.errors[-3:]}"
            )
            assert len(sim.tx_responses) >= max(1, n_expect - 2), (
                f"PC TX chunks {len(sim.tx_responses)} << expect {n_expect}; "
                f"rx={len(sim.rx_requests)} errors={sim.errors[-3:]}"
            )

            # --- B1) IPC received image bytes == line-side sent pixels ---
            arr_ipc = _png_to_gray(got_img["data"])
            assert arr_ipc.shape == pixels.shape, f"IPC shape {arr_ipc.shape} != sim {pixels.shape}"
            mismatch_ipc = int(np.count_nonzero(arr_ipc != pixels))
            assert mismatch_ipc == 0, (
                f"IPC vs TX pixel mismatch count={mismatch_ipc} side={side} board={board}"
            )

            # --- A1) IPC meta resolution == sent params ---
            meta = got_img.get("meta") or {}
            mw = int(meta.get("width") or 0)
            mh = int(meta.get("height") or 0)
            assert (mw, mh) == (side, side), (
                f"IPC meta resolution {(mw, mh)} != sent {(side, side)} board={board}"
            )

            # --- A2) page-parsed displayed resolution == sent params ---
            shown = await camera_wait_displayed_resolution(page, side, timeout_s=25.0)
            shown_norm = (
                shown.replace("\u00d7", "x")
                .replace("\xd7", "x")
                .replace("*", "x")
                .replace("X", "x")
                .replace(" ", "")
                .lower()
            )
            assert shown_norm == f"{side}x{side}" or shown.replace(" ", "") == expect_res_text, (
                f"page displayed resolution {shown!r} != {expect_res_text!r}"
            )

            # --- B2) page-displayed image (cache / vue imageSrc) == TX == IPC ---
            arr_page, page_info = await camera_canvas_gray_array(page, side)
            assert arr_page.shape == pixels.shape, (
                f"page image shape {arr_page.shape} != {pixels.shape}; info={page_info}"
            )
            mismatch_page = int(np.count_nonzero(arr_page != pixels))
            assert mismatch_page == 0, (
                f"page-displayed vs TX pixel mismatch={mismatch_page} "
                f"side={side} board={board} info={page_info}"
            )
            mismatch_page_ipc = int(np.count_nonzero(arr_page != arr_ipc))
            assert mismatch_page_ipc == 0, (
                f"page-displayed vs IPC mismatch={mismatch_page_ipc} side={side}"
            )

        finally:
            try:
                await serial_ui_close(page, ipc_port)
            except Exception as exc:  # noqa: BLE001
                print(f"[HIL] camera image UI close failed: {exc}", flush=True)
    finally:
        try:
            api.stop_camera(ipc_port)
        except Exception:
            pass
        try:
            api.ensure_hardware_idle(reason=f"after camera image {board} {side}", timeout_s=12.0)
        except Exception as exc:  # noqa: BLE001
            print(f"[HIL] idle after camera image failed: {exc}", flush=True)
        sim.stop()
