"""
视频 API 视图
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response

from .serializers import CreateVideoSerializer, MergeVideoSerializer, _resolve_asset_url
from .services import video_generator_service
from .merge_service import merge_videos


class CreateVideoView(APIView):
    """
    POST /ai/video/create
    生成视频或延伸视频，立即返回 taskId
    """

    def post(self, request):
        serializer = CreateVideoSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        task_id = data['taskId']
        task_type = data['task_type']

        kwargs = {
            'task_type': task_type,
            'prompt': data['prompt'],
            'duration': data['duration_int'],
        }
        if task_type == 'reference_to_video':
            resolved = [_resolve_asset_url(u, for_merge=False) for u in data['images']]
            kwargs['ref_imgs'] = ','.join(resolved)
        elif task_type == 'single_shot_extension':
            kwargs['input_video'] = _resolve_asset_url(data['input_video'], for_merge=False)

        result = video_generator_service.create_video(task_id, **kwargs)

        if result["success"]:
            return Response({"code": 200, "msg": "提交成功"}, status=status.HTTP_200_OK)
        return Response(
            {"code": 500, "msg": result["message"]},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class MergeVideoView(APIView):
    """
    POST /ai/video/merge
    视频合成，立即返回 taskId
    """

    def post(self, request):
        serializer = MergeVideoSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        # merge 在 Django 本机执行，local: 指向 MERGE_TEST_ASSETS_DIR（项目 test_assets）
        resolved_urls = [_resolve_asset_url(u, for_merge=True) for u in data['videoUrls']]
        result = merge_videos(data['taskId'], resolved_urls)

        return Response({"code": 200, "msg": "提交成功"}, status=status.HTTP_200_OK)
