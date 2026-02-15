"""
视频生成 API 序列化器
"""
from rest_framework import serializers


class GenerateVideoSerializer(serializers.Serializer):
    """视频生成请求参数"""

    task_type = serializers.CharField(
        default='reference_to_video',
        help_text='任务类型，如 reference_to_video, text_to_video, image_to_video 等',
    )
    model_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='模型路径，不传则使用默认模型',
    )
    ref_imgs = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='参考图片 URL，多个用逗号分隔（reference_to_video 需要）',
    )
    prompt = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text='视频描述提示词',
    )
    duration = serializers.IntegerField(
        default=5,
        min_value=1,
        max_value=10,
        help_text='视频时长（秒）',
    )
    offload = serializers.BooleanField(
        default=True,
        help_text='是否使用 offload 模式',
    )
