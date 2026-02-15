"""
视频生成服务：支持远程 SSH 执行或本机直接执行
"""
import base64
import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import Optional

import paramiko
from scp import SCPClient

from django.conf import settings

logger = logging.getLogger(__name__)


def _escape_shell_arg(s: str) -> str:
    """转义 shell 参数字符串，避免注入和解析错误"""
    return s.replace("\\", "\\\\").replace("'", "'\\''")


class RemoteVideoGeneratorService:
    """视频生成服务（远程 SSH 或本机执行）"""

    def __init__(self):
        self.ssh_client: Optional[paramiko.SSHClient] = None
        self._initialized = False

    def _use_remote_ssh(self) -> bool:
        return getattr(settings, 'USE_REMOTE_SSH', True)

    def _get_ssh_client(self) -> paramiko.SSHClient:
        """获取或创建 SSH 客户端"""
        if self.ssh_client is None or not self._is_connection_alive():
            self._connect()
        return self.ssh_client

    def _is_connection_alive(self) -> bool:
        """检查 SSH 连接是否存活"""
        if self.ssh_client is None:
            return False
        try:
            transport = self.ssh_client.get_transport()
            return transport is not None and transport.is_active()
        except Exception:
            return False

    def _connect(self) -> None:
        """建立 SSH 连接"""
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                pass
            self.ssh_client = None

        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_client.connect(
            hostname=settings.REMOTE_SSH_HOST,
            port=settings.REMOTE_SSH_PORT,
            username=settings.REMOTE_SSH_USER,
            password=settings.REMOTE_SSH_PASSWORD,
            timeout=30,
        )
        logger.info("SSH 连接已建立: %s:%s", settings.REMOTE_SSH_HOST, settings.REMOTE_SSH_PORT)

    def initialize(self) -> bool:
        """
        项目启动时执行初始化
        - 远程模式：测试 SSH 连接
        - 本机模式：跳过
        """
        if not self._use_remote_ssh():
            self._initialized = True
            logger.info("本机执行模式已启用，跳过 SSH 初始化")
            return True
        try:
            client = self._get_ssh_client()
            stdin, stdout, stderr = client.exec_command("echo 'SSH OK'", timeout=10)
            output = stdout.read().decode().strip()
            if output == "SSH OK":
                self._initialized = True
                logger.info("远程服务器初始化成功")
                return True
            return False
        except Exception as e:
            logger.exception("远程服务器初始化失败: %s", e)
            return False

    def _build_command(self, **kwargs) -> str:
        """
        构建完整的执行命令，包含环境初始化和 generate_video.py 调用
        """
        model_id = kwargs.get('model_id') or settings.REMOTE_MODEL_ID
        task_type = kwargs.get('task_type', 'reference_to_video')
        ref_imgs = kwargs.get('ref_imgs', '')
        prompt = kwargs.get('prompt', '')
        duration = kwargs.get('duration', 5)
        offload = kwargs.get('offload', True)

        # 环境变量设置
        # 直接使用 env 下的 python 绝对路径，无需 conda activate
        env_python = f"{settings.REMOTE_WORK_DIR}/env/bin/python"
        env_setup = (
            "source /etc/network_turbo && "
            f"cd {settings.REMOTE_WORK_DIR} && "
            f'export PATH="{settings.REMOTE_WORK_DIR}/env/bin:$PATH" && '
            'export HF_HOME="/root/autodl-tmp/huggingface_cache" && '
            'export MODELSCOPE_CACHE="/root/autodl-tmp/modelscope_cache" && '
            'export TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0" && '
        )

        # 构建 python 命令（使用 env 内 python 绝对路径）
        cmd_parts = [
            f"{settings.REMOTE_WORK_DIR}/env/bin/python", "generate_video.py",
            f"--model_id", f'"{model_id}"',
            "--task_type", task_type,
            "--prompt", f'"{prompt.replace(chr(34), chr(92)+chr(34))}"',  # 转义引号
            "--duration", str(duration),
        ]
        if ref_imgs:
            cmd_parts.extend(["--ref_imgs", f'"{ref_imgs}"'])
        if offload:
            cmd_parts.append("--offload")

        python_cmd = " ".join(cmd_parts)
        full_cmd = env_setup + python_cmd
        return full_cmd

    def _build_command_safe(self, task_id: str, **kwargs) -> str:
        """
        使用更安全的参数拼接方式（单引号包裹，避免特殊字符问题）
        """
        model_id = kwargs.get('model_id') or settings.REMOTE_MODEL_ID
        task_type = kwargs.get('task_type', 'reference_to_video')
        ref_imgs = kwargs.get('ref_imgs', '')
        prompt = kwargs.get('prompt', '')
        duration = kwargs.get('duration', 5)
        offload = kwargs.get('offload', True)

        # 直接使用 env 下的 python 绝对路径，无需 conda activate
        env_setup = (
            "source /etc/network_turbo && "
            f"cd {settings.REMOTE_WORK_DIR} && "
            f'export PATH="{settings.REMOTE_WORK_DIR}/env/bin:$PATH" && '
            'export HF_HOME="/root/autodl-tmp/huggingface_cache" && '
            'export MODELSCOPE_CACHE="/root/autodl-tmp/modelscope_cache" && '
            'export TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0" && '
        )

        args = [
            f"--model_id '{_escape_shell_arg(model_id)}'",
            f"--task_type {task_type}",
            f"--prompt '{_escape_shell_arg(prompt)}'",
            f"--duration {duration}",
            f"--output_file '{task_id}.mp4'",
        ]
        if ref_imgs:
            args.append(f"--ref_imgs '{_escape_shell_arg(ref_imgs)}'")
        if offload:
            args.append("--offload")

        return env_setup + f"{settings.REMOTE_WORK_DIR}/env/bin/python generate_video.py " + " ".join(args)

    def generate_video(self, **kwargs) -> dict:
        """
        提交视频生成任务，后台执行脚本，立即返回流水号
        返回: {"success": bool, "task_id": str|None, "message": str}
        """
        task_id = uuid.uuid4().hex
        try:
            cmd = self._build_command_safe(task_id, **kwargs)
            log_file = f"/tmp/skyreels_{task_id}.log"

            if self._use_remote_ssh():
                return self._submit_via_ssh(task_id, cmd, log_file)
            return self._submit_local(task_id, cmd, log_file)

        except Exception as e:
            logger.exception("视频生成异常: %s", e)
            return {
                "success": False,
                "task_id": None,
                "message": str(e),
            }

    def _submit_via_ssh(self, task_id: str, cmd: str, log_file: str) -> dict:
        """通过 SSH 在远程执行"""
        client = self._get_ssh_client()
        cmd_b64 = base64.b64encode(cmd.encode("utf-8")).decode("ascii")
        background_cmd = f"nohup bash -c 'eval \"$(echo {cmd_b64} | base64 -d)\"' > {log_file} 2>&1 &"
        logger.info("提交视频生成任务 task_id=%s (远程SSH)", task_id)
        stdin, stdout, stderr = client.exec_command(background_cmd, timeout=30)
        stdout_output = stdout.read().decode(errors='replace')
        stderr_output = stderr.read().decode(errors='replace')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            err_msg = (stderr_output or stdout_output)[:500]
            logger.error("提交任务失败 task_id=%s, exit_code=%s", task_id, exit_status)
            return {"success": False, "task_id": None, "message": f"提交任务失败 (exit_code={exit_status}): {err_msg or '(无输出)'}"}
        return {"success": True, "task_id": task_id, "message": "任务已提交，正在后台执行"}

    def _submit_local(self, task_id: str, cmd: str, log_file: str) -> dict:
        """本机直接执行（subprocess 后台，cmd 内已包含 source/export）"""
        logger.info("提交视频生成任务 task_id=%s (本机)", task_id)
        with open(log_file, 'w') as f:
            proc = subprocess.Popen(
                ['bash', '-c', cmd],
                stdout=f,
                stderr=subprocess.STDOUT,
                cwd='/',
            )
        # 稍等检查是否立即失败
        try:
            proc.wait(timeout=2)
            if proc.returncode != 0:
                return {"success": False, "task_id": None, "message": f"启动失败 (exit_code={proc.returncode})，详见 {log_file}"}
        except subprocess.TimeoutExpired:
            pass  # 超时说明进程在跑，正常
        return {"success": True, "task_id": task_id, "message": "任务已提交，正在后台执行"}

    def _copy_latest_mp4(self, ssh_client: paramiko.SSHClient, remote_dir: str) -> Optional[Path]:
        """
        从远程 result/{task_type}/ 目录拷贝时间最晚的 mp4 到本地
        """
        # 确保本地目录存在
        local_base = Path(settings.GENERATED_VIDEOS_DIR)
        local_base.mkdir(parents=True, exist_ok=True)

        # 在远程执行命令找到最新的 mp4（递归搜索子目录）
        remote_full_dir = f"{settings.REMOTE_WORK_DIR}/{remote_dir}"
        # 优先使用 find -printf（GNU find），否则用 ls
        find_cmd = f'find "{remote_full_dir}" -name "*.mp4" -type f -printf "%T@ %p\\n" 2>/dev/null | sort -rn | head -1'
        stdin, stdout, stderr = ssh_client.exec_command(f"bash -c {repr(find_cmd)}", timeout=30)
        output = stdout.read().decode().strip()

        if not output:
            # 备用：stat 获取修改时间后排序
            alt_cmd = f'for f in $(find "{remote_full_dir}" -name "*.mp4" -type f 2>/dev/null); do stat -c "%Y $f" "$f"; done | sort -rn | head -1'
            stdin, stdout, stderr = ssh_client.exec_command(f"bash -c {repr(alt_cmd)}", timeout=30)
            output = stdout.read().decode().strip()
        if not output:
            # 再备用：直接 ls 当前目录（不递归）
            alt_cmd2 = f'ls -t "{remote_full_dir}"/*.mp4 2>/dev/null | head -1'
            stdin, stdout, stderr = ssh_client.exec_command(alt_cmd2, timeout=30)
            output = stdout.read().decode().strip()

        if not output:
            return None

        # 解析远程文件路径
        # find -printf 输出格式: "timestamp /full/path/file.mp4"
        # ls 输出格式: "/full/path/file.mp4"
        parts = output.strip().split(None, 1)
        remote_path = parts[-1].strip() if len(parts) > 1 else output.strip()

        # 生成本地文件名
        filename = os.path.basename(remote_path)
        local_path = local_base / filename

        # 使用 SCP 拷贝
        with SCPClient(ssh_client.get_transport()) as scp:
            scp.get(remote_path, str(local_path))

        logger.info("已拷贝视频到本地: %s", local_path)
        return local_path

    def close(self) -> None:
        """关闭 SSH 连接"""
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                pass
            self.ssh_client = None
        self._initialized = False


# 单例服务实例
video_generator_service = RemoteVideoGeneratorService()
