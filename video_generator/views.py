"""
视频生成 API 视图
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response

from .serializers import GenerateVideoSerializer
from .services import video_generator_service


class GenerateVideoView(APIView):
    """
    POST /api/generate-video/
    根据参数在远程服务器执行视频生成，并将结果拷贝到本地
    """

    def post(self, request):
        serializer = GenerateVideoSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        result = video_generator_service.generate_video(**data)

        if result["success"]:
            return Response(
                {
                    "success": True,
                    "message": result["message"],
                    "task_id": result["task_id"],
                },
                status=status.HTTP_200_OK,
            )
        return Response(
            {
                "success": False,
                "message": result["message"],
                "debug_output": result.get("debug_output"),  # 失败时返回远程输出，便于排查
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
