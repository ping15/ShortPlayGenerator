"""
视频 API 序列化器
"""
import re
from rest_framework import serializers


def _parse_duration(value):
    """解析时长，如 5s -> 5"""
    if value is None:
        return 5
    if isinstance(value, int):
        return value
    s = str(value).strip()
    m = re.match(r'^(\d+)s?$', s, re.I)
    return int(m.group(1)) if m else 5


def _resolve_asset_url(value: str, for_merge: bool = False) -> str:
    """
    解析资源地址：local:images/1.png -> file://{base}/images/1.png
    for_merge=True：视频合成用 MERGE_TEST_ASSETS_DIR（项目 test_assets）
    for_merge=False：视频生成/延伸用 REMOTE_TEST_ASSETS_DIR（/home/test_assets）
    """
    if not value or not value.strip():
        return value
    s = value.strip()
    if s.lower().startswith('local:'):
        subpath = s[6:].lstrip('/')
        from django.conf import settings
        if for_merge:
            base = getattr(settings, 'MERGE_TEST_ASSETS_DIR', settings.BASE_DIR / 'test_assets')
        else:
            base = getattr(settings, 'REMOTE_TEST_ASSETS_DIR', '/home/test_assets')
        base = str(base).replace('\\', '/').rstrip('/')
        prefix = "file://" if base.startswith('/') else "file:///"
        return f"{prefix}{base}/{subpath}"
    return s


class CreateVideoSerializer(serializers.Serializer):
    """视频生成/延伸 请求参数"""

    prompt = serializers.CharField(required=True)
    taskId = serializers.CharField(required=True)
    task_type = serializers.ChoiceField(
        choices=['reference_to_video', 'single_shot_extension'],
        required=True,
    )
    duration = serializers.CharField(default='5s', required=False)
    images = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
    )
    input_video = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        task_type = attrs['task_type']
        if task_type == 'reference_to_video':
            images = attrs.get('images') or []
            if not images:
                raise serializers.ValidationError({'images': 'reference_to_video 需要提供 images'})
        elif task_type == 'single_shot_extension':
            input_video = attrs.get('input_video') or ''
            if not input_video:
                raise serializers.ValidationError({'input_video': 'single_shot_extension 需要提供 input_video'})
        attrs['duration_int'] = _parse_duration(attrs.get('duration', '5s'))
        return attrs


class MergeVideoSerializer(serializers.Serializer):
    """视频合成 请求参数"""

    videoUrls = serializers.ListField(
        child=serializers.CharField(),
        required=True,
        allow_empty=False,
    )
    taskId = serializers.CharField(required=True)
