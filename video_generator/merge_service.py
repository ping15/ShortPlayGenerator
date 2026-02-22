"""
视频合成服务：下载多个视频并合成，完成后上传 OSS、记录 URL、HTTP 通知
"""
import logging
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from threading import Thread

import requests

from django.conf import settings

from .notify_utils import call_notify

logger = logging.getLogger(__name__)

NOTIFY_LOG = getattr(settings, 'NOTIFY_LOG_PATH', '/tmp/shortplay_notify.log')
OSS_URL_LOG = getattr(
    settings, 'OSS_URL_LOG_PATH',
    str(Path(getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent)) / 'test_assets' / 'logs' / 'merged_oss_urls.log'),
)


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
    """同步执行：下载、合成、上传、通知"""
    notify_url = getattr(settings, 'MERGE_NOTIFY_URL', '') or ''

    def _notify(video_url: str, status: str) -> None:
        if notify_url:
            call_notify(notify_url, task_id, video_url, status)

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
                _notify("", "FAIL")
                return
            local_files.append(local)

        if len(local_files) == 0:
            _notify("", "FAIL")
            return
        # 修复 moov atom 在末尾的 MP4（AI 生成/流式输出常见），避免 "moov atom not found"
        # 使用 -probesize/-analyzeduration 让 ffmpeg 读取更多数据以定位末尾的 moov
        fixed_files = []
        for p in local_files:
            fixed = tmp / f"{p.stem}_fixed{p.suffix}"
            r = subprocess.run(
                ['ffmpeg', '-y', '-probesize', '100M', '-analyzeduration', '100M',
                 '-i', str(p), '-c', 'copy', '-movflags', '+faststart', str(fixed)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode == 0:
                fixed_files.append(fixed)
            else:
                logger.error("ffmpeg 无法读取视频文件(可能损坏或 moov 在末尾): %s, stderr: %s", p, r.stderr[:500] if r.stderr else "")
                _notify("", "FAIL")
                return
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
                _notify("", "FAIL")
                return

    logger.info("视频合成成功 taskId=%s -> %s", task_id, out_path)

    oss_url = ""
    secret_id = getattr(settings, 'OSS_ACCESS_KEY_ID', '')
    secret_key = getattr(settings, 'OSS_ACCESS_KEY_SECRET', '')
    bucket_name = getattr(settings, 'OSS_BUCKET_NAME', '')
    _r = (getattr(settings, 'OSS_REGION', '') or 'ap-beijing').strip()
    region = ''.join(c for c in _r if c.isalnum() or c == '-') or 'ap-beijing'
    prefix = getattr(settings, 'OSS_MERGED_PREFIX', 'merged/')

    if secret_id and secret_key and bucket_name:
        try:
            from qcloud_cos import CosConfig, CosS3Client
            cos_timeout = getattr(settings, 'OSS_COS_TIMEOUT', 600)
            cos_part_size = getattr(settings, 'OSS_COS_PART_SIZE', 1)
            cos_max_thread = getattr(settings, 'OSS_COS_MAX_THREAD', 1)
            config = CosConfig(
                Region=region,
                SecretId=secret_id,
                SecretKey=secret_key,
                Timeout=cos_timeout,
            )
            client = CosS3Client(config)
            object_key = f"{prefix.rstrip('/')}/{task_id}.mp4"
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    client.upload_file(
                        Bucket=bucket_name,
                        LocalFilePath=str(out_path),
                        Key=object_key,
                        PartSize=cos_part_size,
                        MAXThread=cos_max_thread,
                        EnableMD5=False,
                    )
                    break
                except Exception as upload_err:
                    if attempt < max_retries - 1:
                        wait_sec = 5 * (attempt + 1)
                        logger.warning("COS上传重试 taskId=%s 第%d次失败，%ds后重试: %s", task_id, attempt + 1, wait_sec, upload_err)
                        time.sleep(wait_sec)
                    else:
                        raise
            oss_url = f"https://{bucket_name}.cos.{region}.myqcloud.com/{object_key}"
            logger.info("COS上传成功 taskId=%s url=%s", task_id, oss_url)
        except Exception as e:
            logger.exception("COS上传失败 taskId=%s: %s", task_id, e)
    else:
        logger.info("COS未配置，跳过上传 taskId=%s", task_id)

    if oss_url and OSS_URL_LOG:
        try:
            Path(OSS_URL_LOG).parent.mkdir(parents=True, exist_ok=True)
            with open(OSS_URL_LOG, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().isoformat()}] taskId={task_id} {oss_url}\n")
        except Exception as e:
            logger.exception("写入OSS URL日志失败: %s", e)

    Path(NOTIFY_LOG).parent.mkdir(parents=True, exist_ok=True)
    with open(NOTIFY_LOG, 'a') as f:
        f.write(f"[NOTIFY] video_merge_done taskId={task_id}\n")

    _notify(oss_url or "", "SUCCESS" if oss_url else "FAIL")


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
