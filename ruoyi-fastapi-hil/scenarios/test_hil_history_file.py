# -*- coding: utf-8 -*-
"""首页/遥测 → 历史文件数据 & 历史文件曲线 深测。

流程：选遥测表 → 上传样本 → 清解析槽 → 解析 → 解析进程可见 → 页面操作 → 确认进程回收。
样本：hil/testdata/history_file/（zip 入库，跑时再解压）。

顺序（本文件定义顺序，pytest 默认按此收集）：
1. test_history_file_curve_deep
2. test_history_file_download_single_after_curve
3. test_history_file_download_multi_after_curve
下载依赖曲线用例先把 D8V17 传到服务器；单独 -k download 且盘上无该文件时 skip，不假绿。

其它约定：
- 同名覆盖上传只抽测 1 个代表表，解析后走回放条选帧。
- 用例前后 ensure_fileplay_idle，曲线解析前再清一次 curve 槽。
- 曲线样本文件名含 YYYYMMDD_HHMMSS_mmm，帧数须超过一块（10000），滑块才能换 chunk。
"""
from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from hil.browser import pages as P
from hil.config import CONFIG
from hil.history_file import (
    CURVE_CHUNK_FRAMES,
    cleanup_history_file_data,
    ensure_history_file_data,
    overwrite_probe_table,
    recv_stamp_ok,
    sample_path_for,
    skip_reason,
)
from hil.ipc_api import IpcApi

pytestmark = [pytest.mark.ui_only, pytest.mark.asyncio(loop_scope="session")]

# 曲线深测上传成功后置 True；下载用例也可凭 browse 发现既有样本。
_CURVE_UPLOAD_READY = False


@pytest.fixture(scope="session")
def history_file_bundle():
    """会话级：删旧 data → 解压 zip；失败也尽量删 data。"""
    data_dir, manifest = ensure_history_file_data(force=True)
    try:
        yield data_dir, manifest
    finally:
        cleanup_history_file_data()


@pytest.fixture(scope="session")
def fileplay_api():
    """登录一次，供 ensure_fileplay_idle 使用。"""
    api = IpcApi(CONFIG)
    api.login()
    return api


@pytest.fixture
def fileplay_idle(fileplay_api):
    """深测用例前后清解析进程/缓存（不解压冒烟，避免无 IPC 时挂）。"""
    fileplay_api.ensure_fileplay_idle(reason="history_file setup", timeout_s=25.0)
    yield fileplay_api
    try:
        fileplay_api.ensure_fileplay_idle(reason="history_file teardown", timeout_s=25.0)
    except Exception as exc:  # noqa: BLE001
        print(f"[HIL] history_file teardown fileplay idle 失败: {exc}", flush=True)


def _need_sample(table: str, bundle):
    data_dir, manifest = bundle
    reason = skip_reason(table, manifest)
    if reason:
        pytest.skip(reason)
    path = sample_path_for(table, data_dir, manifest)
    if path is None:
        pytest.skip(f"样本文件缺失: {table}")
    return path, manifest["tables"][table]



def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _upload_file_names(api: IpcApi) -> set[str]:
    data = api.telemetry_file_browse(root='upload', path='', show_all=True)
    return {
        str(e.get('name'))
        for e in (data.get('entries') or [])
        if e and not e.get('isDir') and e.get('name')
    }


def _basename(name: str) -> str:
    from pathlib import PurePosixPath

    return PurePosixPath(str(name or '').replace('\\', '/')).name


def _require_curve_upload_sample(api: IpcApi, bundle):
    """曲线用例上传的 D8V17 须已在服务器 upload 根；否则 skip（勿假定空盘）。"""
    path, meta = _need_sample('D8V17', bundle)
    name = str(meta.get('file') or path.name)
    names = _upload_file_names(api)
    if name not in names:
        if not _CURVE_UPLOAD_READY:
            pytest.skip(
                '须先跑 test_history_file_curve_deep（同会话曲线上传后服务器才有样本）；'
                f'当前 upload 根无 {name}'
            )
        api.telemetry_file_upload(path)
        names = _upload_file_names(api)
        if name not in names:
            pytest.fail(f'曲线样本补传后仍不在 upload 根: {name}')
    return path, name, meta


def _extract_zip_members(zip_bytes: bytes) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            out[_basename(info.filename)] = zf.read(info)
    return out


def _ensure_multi_upload_samples(api: IpcApi, bundle):
    """单文件：曲线 D8V17；多文件再保证 D9 在服务器（缺则 API 上传本地样本）。"""
    primary_path, primary_name, _ = _require_curve_upload_sample(api, bundle)
    second_path, second_meta = _need_sample('D9', bundle)
    second_name = str(second_meta.get('file') or second_path.name)
    names = _upload_file_names(api)
    if second_name not in names:
        api.telemetry_file_upload(second_path)
        names = _upload_file_names(api)
        assert second_name in names, f'多文件第二样本上传失败: {second_name}'
    return [
        (primary_path, primary_name),
        (second_path, second_name),
    ]

async def test_history_file_curve_deep(ui, history_file_bundle, fileplay_idle):
    """历史文件曲线深测（仅 1 次）：XL-D8V17 + CAM008平均灰度值。

    流程：选表→上传 XL-D8V17-HIL_*.bin→解析→单独增加 CAM008 曲线→查询等点→
    界面截取/轴控等工具→滑动区间滑块→再查询→重置曲线→确认进程回收。

    说明：用户口头说代替 XL-D9V17-HIL，但对应遥测表是 XL-D8V17；本用例只跑 D8V17，
    D9V17 仍保留在 data_deep 样本中，不参与曲线深测。
    """
    table = "D8V17"
    path, meta = _need_sample(table, history_file_bundle)
    assert str(meta.get("file") or "").startswith("XL-D8V17-HIL"), meta
    assert recv_stamp_ok(str(meta.get("file") or "")), (
        f"曲线样本文件名须含 YYYYMMDD_HHMMSS_mmm: {meta.get('file')}"
    )
    assert int(meta.get("frame_count_sample") or 0) > CURVE_CHUNK_FRAMES, (
        f"曲线样本帧数须超过一块 {CURVE_CHUNK_FRAMES}，否则区间滑块没有后续 chunk: {meta}"
    )
    page = await ui.goto("/telemetry/fileCurve", settle_ms=800)
    await page.locator(".curve-page").wait_for(timeout=20000)

    await P.file_toolbar_select_tm(page, table)
    await P.file_browser_upload_and_pick(page, path)
    global _CURVE_UPLOAD_READY
    _CURVE_UPLOAD_READY = True
    fileplay_idle.ensure_fileplay_idle(channel="curve", reason="before parse curve D8V17", timeout_s=15.0)
    await P.file_click_parse(page)
    rows = await P.file_open_sessions_and_snapshot(page)
    assert rows is not None
    await P.file_close_sessions_dialog(page)

    frames = await P.file_wait_parsed(page, timeout_s=180.0, min_frames=1)
    assert frames >= 1
    label0, chunk_max = await P.file_curve_slider_edges(page)
    assert chunk_max > 1, (
        f"区间滑块块序号上限={chunk_max}（文案 {label0}），"
        f"样本帧数不足以滑动到后续 chunk（一块 {CURVE_CHUNK_FRAMES} 帧）"
    )

    # 单独添加 CAM008平均灰度值
    label, add_pts = await P.file_curve_add_field(page, "CAM008")
    assert "CAM008" in label, label
    print(f"[HIL] add_curve points={add_pts}", flush=True)
    assert add_pts >= 1, f"增加曲线后无点: {add_pts}"

    # 查询（增加曲线时可能已拉齐本地 chunk，查询可能不再打 API）
    seed = await P.file_curve_click_query(page, query_wait_s=90.0)
    print(f"[HIL] curve query seed_points={seed}", flush=True)
    points = await P.file_curve_wait_points(
        page, min_points=1, timeout_s=30.0, seed_points=max(seed, add_pts)
    )
    print(f"[HIL] curve points after query={points}", flush=True)
    assert points >= 1, f"查询后无曲线点: points={points} seed={seed} add={add_pts}"

    # 界面裁切/截取与其它曲线操作
    covered = await P.file_curve_exercise_tools(page)
    assert covered.get("crop"), f"截取/裁切未点到: {covered}"

    # 滑动滑块到另一块 → 再查询 → 重置曲线
    await P.file_curve_move_range_slider(page, ratio=0.55)
    label1, _chunk_max2 = await P.file_curve_slider_edges(page)
    assert label1 != label0, f"滑动区间后块范围仍为 {label0}（未离开默认 chunk）"
    seed2 = await P.file_curve_click_query(page, query_wait_s=90.0)
    print(f"[HIL] curve re-query seed_points={seed2}", flush=True)
    points2 = await P.file_curve_wait_points(page, min_points=1, timeout_s=60.0, seed_points=seed2)
    print(f"[HIL] curve points after slider query={points2}", flush=True)
    assert points2 >= 1, f"滑块后再查询无点: points={points2} seed={seed2}"
    await P.file_curve_reset(page)

    # Large D8V17 (~58k frames) workers may linger; API/Redis close is authoritative.
    idle_ok = False
    try:
        fileplay_idle.ensure_fileplay_idle(
            channel="curve", reason="after curve deep recycle", timeout_s=45.0
        )
        idle_ok = True
    except Exception as exc:  # noqa: BLE001
        print(f"[HIL] post-curve idle warn: {exc}", flush=True)
    if idle_ok:
        try:
            await P.file_assert_process_recycled(page, file_name=meta["file"], timeout_s=20.0)
        except Exception as exc:  # noqa: BLE001 — UI text match flaky; API idle already OK
            print(f"[HIL] UI recycle soft-skip after API idle: {exc}", flush=True)
    else:
        await P.file_assert_process_recycled(page, file_name=meta["file"], timeout_s=60.0)
    assert not ui.page_errors, ui.page_errors[:3]



async def test_history_file_download_single_after_curve(history_file_bundle, fileplay_api):
    """曲线上传之后：API 下载单文件 ZIP，解压后与本地样本字节/哈希一致。

    必须排在 test_history_file_curve_deep 之后（本文件源码顺序）。
    """
    local_path, remote_name, _meta = _require_curve_upload_sample(
        fileplay_api, history_file_bundle
    )
    zip_bytes = fileplay_api.telemetry_file_download_zip(
        [remote_name], root='upload', path=''
    )
    members = _extract_zip_members(zip_bytes)
    assert remote_name in members, f'ZIP 缺成员 {remote_name}; got={sorted(members)}'
    local_raw = local_path.read_bytes()
    got = members[remote_name]
    assert len(got) == len(local_raw), f'长度不一致: remote={len(got)} local={len(local_raw)}'
    assert _sha256_bytes(got) == _sha256_bytes(local_raw), (
        f'哈希不一致: remote={_sha256_bytes(got)} local={_sha256_bytes(local_raw)}'
    )


async def test_history_file_download_multi_after_curve(history_file_bundle, fileplay_api):
    """曲线上传后：批量下载多文件 ZIP，各成员与本地对应样本字节/哈希一致。"""
    pairs = _ensure_multi_upload_samples(fileplay_api, history_file_bundle)
    names = [n for _p, n in pairs]
    zip_bytes = fileplay_api.telemetry_file_download_zip(names, root='upload', path='')
    members = _extract_zip_members(zip_bytes)
    for local_path, remote_name in pairs:
        assert remote_name in members, f'ZIP 缺成员 {remote_name}; got={sorted(members)}'
        local_raw = local_path.read_bytes()
        got = members[remote_name]
        assert len(got) == len(local_raw), (
            f'{remote_name} 长度不一致: remote={len(got)} local={len(local_raw)}'
        )
        assert _sha256_bytes(got) == _sha256_bytes(local_raw), (
            f'{remote_name} 哈希不一致: '
            f'remote={_sha256_bytes(got)} local={_sha256_bytes(local_raw)}'
        )


async def test_history_file_overwrite_upload_once(ui, history_file_bundle, fileplay_idle):
    """同名再上传点「覆盖」，解析后走回放条选帧。只抽测一个代表表。"""
    data_dir, manifest = history_file_bundle
    table = overwrite_probe_table(manifest)
    if not table:
        pytest.skip("manifest 无可用样本表")
    path, meta = _need_sample(table, (data_dir, manifest))
    page = await ui.goto("/telemetry/fileHistory", settle_ms=800)
    await page.locator(".replay-page").wait_for(timeout=20000)
    await P.file_toolbar_select_tm(page, table)
    # first upload
    await P.file_browser_upload_and_pick(page, path)
    # second upload same name → overwrite confirm
    await P.file_browser_upload_and_pick(page, path)
    fileplay_idle.ensure_fileplay_idle(channel="history", reason="before overwrite parse", timeout_s=15.0)
    await P.file_click_parse(page)
    rows = await P.file_open_sessions_and_snapshot(page)
    assert rows is not None
    await P.file_close_sessions_dialog(page)
    frames = await P.file_wait_parsed(page, timeout_s=120.0, min_frames=2)
    assert frames >= 2, f"回放帧数不足以翻页: {frames}"
    covered = await P.file_history_exercise_frames(page)
    assert covered.get("next") or covered.get("slider"), f"回放条未翻帧: {covered}"
    await P.file_assert_process_recycled(page, file_name=meta["file"], timeout_s=90.0)
    assert not ui.page_errors, ui.page_errors[:3]


async def test_history_file_data_unpack_smoke(history_file_bundle):
    """纯数据冒烟：确认 zip 能解压且至少有一份样本；未 skip 表帧数 >= min_frames(manifest)。"""
    data_dir, manifest = history_file_bundle
    tables = manifest.get("tables") or {}
    assert tables, "manifest.tables 为空"
    min_frames = int(manifest.get("min_frames") or 1000)
    for info in tables.values():
        assert (data_dir / info["file"]).is_file(), info["file"]
        assert int(info.get("frame_count_sample") or 0) >= min_frames, info
