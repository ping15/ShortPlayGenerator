"""
视频生成服务：支持远程 SSH 执行或本机直接执行，单卡串行队列，文件持久化
"""
import base64
import json
import logging
import os
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Lock, Thread
from typing import Optional

import paramiko
from scp import SCPClient

from django.conf import settings

from .notify_utils import call_notify

logger = logging.getLogger(__name__)

NOTIFY_LOG = getattr(settings, 'NOTIFY_LOG_PATH', '/tmp/shortplay_notify.log')


def _get_queue_file_path() -> Path:
    """队列持久化文件路径：test_assets/logs/video_gen_queue.jsonl"""
    base = getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent)
    p = base / 'test_assets' / 'logs' / 'video_gen_queue.jsonl'
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _persist_append(task_id: str, kwargs: dict) -> None:
    """任务入队时追加到文件"""
    with _persist_lock:
        with open(_get_queue_file_path(), 'a', encoding='utf-8') as f:
            f.write(json.dumps({'task_id': task_id, 'kwargs': kwargs}, ensure_ascii=False) + '\n')


def _persist_remove(task_id: str) -> None:
    """任务完成后从文件移除"""
    with _persist_lock:
        path = _get_queue_file_path()
        if not path.exists():
            return
        lines = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get('task_id') != task_id:
                        lines.append(line)
                except json.JSONDecodeError:
                    continue
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + ('\n' if lines else ''))


def _persist_load() -> list:
    """启动时加载未完成任务"""
    path = _get_queue_file_path()
    if not path.exists():
        return []
    tasks = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                tasks.append((obj['task_id'], obj.get('kwargs', {})))
            except (json.JSONDecodeError, KeyError):
                continue
    return tasks


_persist_lock = Lock()


def _upload_video_to_cos_and_log(local_path: Path, task_id: str, prefix: str, log_path: str) -> str:
    """上传视频到腾讯云 COS 并记录 URL 到日志，返回 oss_url（失败返回空串）"""
    secret_id = getattr(settings, 'OSS_ACCESS_KEY_ID', '')
    secret_key = getattr(settings, 'OSS_ACCESS_KEY_SECRET', '')
    bucket_name = getattr(settings, 'OSS_BUCKET_NAME', '')
    _r = (getattr(settings, 'OSS_REGION', '') or 'ap-beijing').strip()
    region = ''.join(c for c in _r if c.isalnum() or c == '-') or 'ap-beijing'
    if not all([secret_id, secret_key, bucket_name]) or not local_path.exists():
        return ""
    try:
        from qcloud_cos import CosConfig, CosS3Client
        config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
        client = CosS3Client(config)
        object_key = f"{prefix.rstrip('/')}/{task_id}.mp4"
        client.upload_file(
            Bucket=bucket_name,
            LocalFilePath=str(local_path),
            Key=object_key,
        )
        oss_url = f"https://{bucket_name}.cos.{region}.myqcloud.com/{object_key}"
        logger.info("视频生成 COS上传成功 task_id=%s url=%s", task_id, oss_url)
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().isoformat()}] taskId={task_id} {oss_url}\n")
        return oss_url
    except Exception as e:
        logger.exception("视频生成 COS上传失败 task_id=%s: %s", task_id, e)
        return ""


def _get_exit_code_desc(exit_code: int) -> str:
    """常见退出码说明"""
    if exit_code == 0:
        return "正常结束"
    if exit_code == 1:
        return "一般错误（如参数错误、GPU OOM、模型加载失败、推理异常等）"
    if exit_code == 137:
        return "通常为内存不足被杀（OOM Killed）"
    if exit_code == 139:
        return "段错误（Segmentation fault），可能是显存溢出或驱动问题"
    if exit_code == 143:
        return "进程被 SIGTERM 终止"
    if exit_code == -9:
        return "进程被强制杀死（SIGKILL）"
    return f"异常退出(exit={exit_code})"


def _write_failed_log(task_id: str, reason: str, extra: str = "") -> None:
    """生成失败时写入 test_assets/logs/{task_id}_failed.log"""
    try:
        base = getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent)
        path = base / 'test_assets' / 'logs' / f'{task_id}_failed.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"[{datetime.now().isoformat()}] task_id={task_id} 生成失败\n")
            f.write(f"原因: {reason}\n")
            if extra:
                f.write("\n--- 详细日志 ---\n")
                f.write(extra)
    except Exception as e:
        logger.exception("写入失败日志异常 task_id=%s: %s", task_id, e)


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
        reference_to_video: 仅用 images(->ref_imgs)
        single_shot_extension: 仅用 input_video
        """
        model_id = kwargs.get('model_id') or settings.REMOTE_MODEL_ID
        task_type = kwargs.get('task_type', 'reference_to_video')
        prompt = kwargs.get('prompt', '')
        duration = kwargs.get('duration', 5)
        offload = kwargs.get('offload', True)

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
        if task_type == 'reference_to_video':
            ref_imgs = kwargs.get('ref_imgs', '')
            if ref_imgs:
                args.append(f"--ref_imgs '{_escape_shell_arg(ref_imgs)}'")
        elif task_type == 'single_shot_extension':
            input_video = kwargs.get('input_video', '')
            if input_video:
                args.append(f"--input_video '{_escape_shell_arg(input_video)}'")
        if offload:
            args.append("--offload")

        python_cmd = env_setup + f"{settings.REMOTE_WORK_DIR}/env/bin/python generate_video.py " + " ".join(args)
        notify_cmd = f" && echo '[NOTIFY] video_create_done taskId={task_id}' >> {NOTIFY_LOG}"
        return python_cmd + notify_cmd

    def create_video(self, task_id: str, **kwargs) -> dict:
        """
        提交视频生成任务到队列，立即返回；队列 worker 串行执行，单卡不并发
        任务持久化到文件，关机重启后可恢复
        返回: {"success": bool, "task_id": str|None, "message": str}
        """
        try:
            kw = dict(kwargs)
            _persist_append(task_id, kw)
            _video_gen_queue.put((task_id, kw))
            logger.info("视频生成任务已入队 task_id=%s (队列等待中)", task_id)
            return {"success": True, "task_id": task_id, "message": "任务已入队，正在排队执行"}
        except Exception as e:
            logger.exception("视频生成异常: %s", e)
            return {
                "success": False,
                "task_id": task_id,
                "message": str(e),
            }

    def _get_result_dir(self, task_type: str) -> str:
        """按 task_type 获取结果目录"""
        if task_type == 'single_shot_extension':
            return getattr(settings, 'REMOTE_RESULT_DIR_SINGLE_SHOT_EXTENSION', '')
        return getattr(settings, 'REMOTE_RESULT_DIR_REFERENCE_TO_VIDEO', '')

    def _check_mp4_exists_ssh(self, client, task_id: str, task_type: str) -> bool:
        """远程模式：检查 taskId.mp4 是否存在"""
        result_dir = self._get_result_dir(task_type)
        if not result_dir:
            return True
        mp4_path = f"{result_dir.rstrip('/')}/{task_id}.mp4"
        try:
            stdin, stdout, _ = client.exec_command(f"test -f {repr(mp4_path)} && echo ok", timeout=5)
            return stdout.read().decode().strip() == 'ok'
        except Exception:
            return False

    def _check_mp4_exists_local(self, task_id: str, task_type: str) -> bool:
        """本机模式：检查 taskId.mp4 是否存在"""
        result_dir = self._get_result_dir(task_type)
        if not result_dir:
            return True
        return (Path(result_dir) / f"{task_id}.mp4").exists()

    def _copy_task_mp4_from_remote(self, client, task_id: str, task_type: str) -> Optional[Path]:
        """从远程拷贝 taskId.mp4 到本地 GENERATED_VIDEOS_DIR"""
        result_dir = self._get_result_dir(task_type)
        if not result_dir:
            return None
        remote_path = f"{result_dir.rstrip('/')}/{task_id}.mp4"
        local_base = Path(settings.GENERATED_VIDEOS_DIR)
        local_base.mkdir(parents=True, exist_ok=True)
        local_path = local_base / f"{task_id}.mp4"
        try:
            with SCPClient(client.get_transport()) as scp:
                scp.get(remote_path, str(local_path))
            return local_path
        except Exception as e:
            logger.warning("从远程拷贝视频失败 task_id=%s: %s", task_id, e)
            return None

    def _run_via_ssh_sync(self, task_id: str, cmd: str, log_file: str, task_type: str = 'reference_to_video') -> None:
        """同步执行：远程运行命令并等待完成（队列 worker 用）"""
        client = self._get_ssh_client()
        cmd_b64 = base64.b64encode(cmd.encode("utf-8")).decode("ascii")
        sync_cmd = f"bash -c 'eval \"$(echo {cmd_b64} | base64 -d)\"' > {log_file} 2>&1"
        logger.info("开始执行视频生成 task_id=%s (远程)", task_id)
        stdin, stdout, stderr = client.exec_command(sync_cmd, timeout=7200)
        stdout.read()
        exit_status = stdout.channel.recv_exit_status()
        notify_url = (getattr(settings, 'VIDEO_CREATE_NOTIFY_URL', '') or '').strip()
        if exit_status != 0:
            _exit_desc = _get_exit_code_desc(exit_status)
            logger.warning("视频生成 task_id=%s 退出码: %s（%s）", task_id, exit_status, _exit_desc)
            extra = ""
            try:
                tail_cmd = f"tail -200 {log_file} 2>/dev/null || cat {log_file} 2>/dev/null"
                stdin2, stdout2, _ = client.exec_command(tail_cmd, timeout=10)
                extra = stdout2.read().decode(errors='replace')
            except Exception:
                pass
            _write_failed_log(
                task_id,
                f"远程脚本退出码 {exit_status}，{_exit_desc}。详细错误见下方日志（远程: {log_file}）",
                extra,
            )
            if notify_url:
                call_notify(notify_url, task_id, "", "FAIL")
        elif not self._check_mp4_exists_ssh(client, task_id, task_type):
            _write_failed_log(
                task_id,
                f"脚本退出码 0 但未找到 {task_id}.mp4（路径: {self._get_result_dir(task_type)}）",
                "请检查 generate_video.py 的输出目录配置",
            )
            if notify_url:
                call_notify(notify_url, task_id, "", "FAIL")
        else:
            logger.info("视频生成完成 task_id=%s", task_id)
            oss_url = ""
            local_path = self._copy_task_mp4_from_remote(client, task_id, task_type)
            if local_path:
                prefix = getattr(settings, 'OSS_CREATE_PREFIX', 'generated/')
                log_path = getattr(settings, 'OSS_CREATE_URL_LOG_PATH', '')
                oss_url = _upload_video_to_cos_and_log(local_path, task_id, prefix, log_path)
            if notify_url:
                call_notify(notify_url, task_id, oss_url or "", "SUCCESS" if oss_url else "FAIL")

    def _run_local_sync(self, task_id: str, cmd: str, log_file: str, task_type: str = 'reference_to_video') -> None:
        """同步执行：本机运行命令并等待完成（队列 worker 用）"""
        logger.info("开始执行视频生成 task_id=%s (本机)", task_id)
        with open(log_file, 'w') as f:
            result = subprocess.run(
                ['bash', '-c', cmd],
                stdout=f,
                stderr=subprocess.STDOUT,
                cwd='/',
                timeout=7200,
            )
        notify_url = (getattr(settings, 'VIDEO_CREATE_NOTIFY_URL', '') or '').strip()
        if result.returncode != 0:
            _exit_desc = _get_exit_code_desc(result.returncode)
            logger.warning("视频生成 task_id=%s 退出码: %s（%s）", task_id, result.returncode, _exit_desc)
            extra = ""
            try:
                p = Path(log_file)
                if p.exists():
                    with open(p, 'r', encoding='utf-8', errors='replace') as rf:
                        content = rf.read()
                        extra = content[-20000:]
            except Exception:
                pass
            _write_failed_log(
                task_id,
                f"本机脚本退出码 {result.returncode}，{_exit_desc}。详细错误见下方日志（{log_file}）",
                extra,
            )
            if notify_url:
                call_notify(notify_url, task_id, "", "FAIL")
        elif not self._check_mp4_exists_local(task_id, task_type):
            _write_failed_log(
                task_id,
                f"脚本退出码 0 但未找到 {task_id}.mp4（路径: {self._get_result_dir(task_type)}）",
                "请检查 generate_video.py 的输出目录配置",
            )
            if notify_url:
                call_notify(notify_url, task_id, "", "FAIL")
        else:
            logger.info("视频生成完成 task_id=%s", task_id)
            oss_url = ""
            result_dir = self._get_result_dir(task_type)
            if result_dir:
                local_path = Path(result_dir) / f"{task_id}.mp4"
                prefix = getattr(settings, 'OSS_CREATE_PREFIX', 'generated/')
                log_path = getattr(settings, 'OSS_CREATE_URL_LOG_PATH', '')
                oss_url = _upload_video_to_cos_and_log(local_path, task_id, prefix, log_path)
            if notify_url:
                call_notify(notify_url, task_id, oss_url or "", "SUCCESS" if oss_url else "FAIL")

    def _submit_via_ssh(self, task_id: str, cmd: str, log_file: str, _context: str = "") -> dict:
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

    def _submit_local(self, task_id: str, cmd: str, log_file: str, _context: str = "") -> dict:
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


def _video_gen_worker():
    """队列 worker：串行执行视频生成任务，单卡不并发"""
    while True:
        item = _video_gen_queue.get()
        if item is None:
            _video_gen_queue.task_done()
            break
        task_id, kwargs = item
        try:
            task_type = kwargs.get('task_type', 'reference_to_video')
            cmd = video_generator_service._build_command_safe(task_id, **kwargs)
            log_file = f"/tmp/skyreels_{task_id}.log"
            if video_generator_service._use_remote_ssh():
                video_generator_service._run_via_ssh_sync(task_id, cmd, log_file, task_type)
            else:
                video_generator_service._run_local_sync(task_id, cmd, log_file, task_type)
        except Exception as e:
            logger.exception("视频生成任务异常 task_id=%s: %s", task_id, e)
            _write_failed_log(task_id, f"异常: {e}", traceback.format_exc())
        finally:
            _persist_remove(task_id)
            _video_gen_queue.task_done()


_video_gen_queue = Queue()
for tid, kw in _persist_load():
    _video_gen_queue.put((tid, kw))
    logger.info("恢复未完成任务 task_id=%s", tid)
_video_gen_worker_thread = Thread(target=_video_gen_worker, daemon=True)
_video_gen_worker_thread.start()
