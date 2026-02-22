"""任务完成 HTTP 通知"""
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def call_notify(url: str, task_id: str, video_url: str, status: str) -> bool:
    """
    POST 通知接口
    :param url: 通知地址
    :param task_id: 任务ID
    :param video_url: 视频URL（失败可为空）
    :param status: SUCCESS 或 FAIL
    :return: 是否调用成功（HTTP 200）
    """
    if not url or not url.strip():
        return False
    try:
        resp = requests.post(
            url.strip(),
            json={
                "taskId": task_id,
                "videoUrl": video_url or "",
                "status": status,
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        ok = resp.status_code == 200
        if ok:
            print("通知接口200成功 taskId=%s url=%s status=%s videoUrl=%s", task_id, url, status, video_url or "")
            logger.info("通知接口200成功 taskId=%s url=%s status=%s videoUrl=%s", task_id, url, status, video_url or "")
        else:
            logger.warning("通知接口非200 taskId=%s url=%s status=%s videoUrl=%s", task_id, url, resp.status_code, video_url or "")
        return ok
    except Exception as e:
        logger.exception("通知接口调用失败 taskId=%s url=%s videoUrl=%s: %s", task_id, url, video_url or "", e)
        return False
