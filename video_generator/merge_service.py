"""
视频合成服务：下载多个视频并合成
"""
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Thread

import requests

from django.conf import settings

logger = logging.getLogger(__name__)

NOTIFY_LOG = getattr(settings, 'NOTIFY_LOG_PATH', '/tmp/shortplay_notify.log')


def _download_file(url: str, path: Path, timeout: int = 300) -> bool:
    """下载文件到本地，支持 file:// 和 http(s)://"""
    try:
        if url.startswith('file://'):
            import shutil
            path_str = url[7:]
            # file:///D:/path 在 Windows 上 Path('/D:/path') 会变成 \D:\path 而失效，需去掉前导 /
            if path_str.startswith('/') and len(path_str) > 2 and path_str[2] == ':':
                path_str = path_str[1:]
            src = Path(path_str)
            if not src.exists():
                logger.error("本地文件不存在: %s", src)
                return False
            shutil.copy2(src, path)
            return True
        r = requests.get(url, stream=True, timeout=timeout)
        r.raise_for_status()
        with open(path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        logger.exception("下载失败 %s: %s", url, e)
        return False


def _merge_videos_sync(task_id: str, video_urls: list) -> None:
    """同步执行：下载、合成、通知"""
    out_dir = Path(settings.GENERATED_VIDEOS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{task_id}.mp4"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        local_files = []
        for i, url in enumerate(video_urls):
            ext = '.mp4' if '.mp4' in url.lower() else '.mp4'
            local = tmp / f"part_{i:03d}{ext}"
            if not _download_file(url, local):
                logger.error("视频合成失败：下载失败 taskId=%s url=%s", task_id, url)
                return
            local_files.append(local)

        if len(local_files) == 0:
            return
        # 修复 moov atom 在末尾的 MP4（AI 生成/流式输出常见），避免 "moov atom not found"
        fixed_files = []
        for p in local_files:
            fixed = tmp / f"{p.stem}_fixed{p.suffix}"
            r = subprocess.run(
                ['ffmpeg', '-y', '-i', str(p), '-c', 'copy', '-movflags', '+faststart', str(fixed)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode == 0:
                fixed_files.append(fixed)
            else:
                fixed_files.append(p)
        if len(local_files) == 1:
            import shutil
            shutil.copy(fixed_files[0], out_path)
        else:
            concat_file = tmp / "concat.txt"
            with open(concat_file, 'w') as f:
                for p in fixed_files:
                    f.write(f"file '{p.absolute()}'\n")
            result = subprocess.run(
                ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_file), '-c', 'copy', str(out_path)],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0:
                logger.error("ffmpeg 合成失败 taskId=%s: %s", task_id, result.stderr)
                return

    logger.info("视频合成成功 taskId=%s -> %s", task_id, out_path)
    time.sleep(2)  # 模拟上传 OSS
    logger.info("oss上传成功 taskId=%s", task_id)
    time.sleep(1)  # 模拟调用回调接口
    logger.info("通知成功 taskId=%s", task_id)
    Path(NOTIFY_LOG).parent.mkdir(parents=True, exist_ok=True)
    with open(NOTIFY_LOG, 'a') as f:
        f.write(f"[NOTIFY] video_merge_done taskId={task_id}\n")


def merge_videos(task_id: str, video_urls: list) -> dict:
    """
    提交视频合成任务，后台执行，立即返回
    """
    def _run():
        _merge_videos_sync(task_id, video_urls)

    t = Thread(target=_run)
    t.daemon = True
    t.start()
    return {"success": True, "task_id": task_id, "message": "任务已提交，正在后台执行"}
