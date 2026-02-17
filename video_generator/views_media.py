"""
本地测试资源服务：无 OSS 时用本地文件测试
"""
import os
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse, HttpResponseForbidden


def serve_test_asset(request, subpath: str):
    """
    提供 MERGE_TEST_ASSETS_DIR 目录下的文件访问（项目 test_assets）
    GET /media/test/images/1.png -> test_assets/images/1.png
    """
    base = Path(settings.MERGE_TEST_ASSETS_DIR).resolve()
    base.mkdir(parents=True, exist_ok=True)
    subpath = subpath.lstrip('/')
    if '..' in subpath or subpath.startswith('/'):
        return HttpResponseForbidden("禁止路径穿越")
    full_path = (base / subpath).resolve()
    if not str(full_path).startswith(str(base)):
        return HttpResponseForbidden("禁止路径穿越")
    if not full_path.exists() or not full_path.is_file():
        return HttpResponse(status=404)

    return FileResponse(open(full_path, 'rb'), as_attachment=False, filename=full_path.name)
