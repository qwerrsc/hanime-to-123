"""
后台监控服务
负责监控下载进度和处理重命名任务
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict
from loguru import logger

from api.models import TaskStatus
from services.task_manager import get_task_manager
from services.pan123_service import (
    Pan123AuthService,
    Pan123DownloadService,
    Pan123FolderService
)
from config import get_config
from services.auth_manager import get_auth_manager
from services.user_manager import get_user_manager


def _log_to_user(task_data, message: str, level: str = "info"):
    """记录用户日志"""
    user_id = task_data.user_id or "global"
    try:
        from api.user_logger import add_user_log_handler
        add_user_log_handler(user_id)
        user_logger = logger.bind(user_id=user_id)
        if level == "info":
            user_logger.info(message)
        elif level == "warning":
            user_logger.warning(message)
        elif level == "error":
            user_logger.error(message)
    except Exception as e:
        logger.warning(f"记录用户日志失败: {e}")


class MonitorService:
    """后台监控服务"""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # 移除重复的 _auth_services 缓存，统一使用 auth_manager 的缓存
        self._last_cleanup_time: Optional[datetime] = None  # 上次清理时间

    async def start(self):
        """启动监控服务"""
        if self._running:
            logger.warning("监控服务已在运行")
            return

        self._running = True
        logger.info("监控服务已启动")
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """停止监控服务"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("监控服务已停止")

    async def _monitor_loop(self):
        """监控主循环"""
        config = get_config()

        while self._running:
            try:
                await self.check_all_tasks()
                # 清理已完成超过1小时的任务（每10分钟执行一次，避免频繁输出日志）
                now = datetime.now()
                if (self._last_cleanup_time is None or 
                    (now - self._last_cleanup_time).total_seconds() >= 600):  # 10分钟
                    await self._cleanup_completed_tasks()
                    self._last_cleanup_time = now
            except Exception as e:
                import traceback
                error_detail = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
                logger.error(f"监控任务时出错: {error_detail}")
                logger.debug(f"异常堆栈: {traceback.format_exc()}")

            # 等待下一次检查
            await asyncio.sleep(config.monitoring.check_interval)

    async def check_all_tasks(self):
        """检查所有任务状态"""
        task_manager = get_task_manager()

        # 获取所有进行中的任务，按 user_id 分组
        tasks_by_user = {}
        for task_data in task_manager.list_tasks():
            if task_data.status not in [TaskStatus.DOWNLOADING.value, TaskStatus.RENAMING.value]:
                continue

            user_id = task_data.user_id or "global"
            if user_id not in tasks_by_user:
                tasks_by_user[user_id] = []
            tasks_by_user[user_id].append(task_data)

        # 如果没有进行中的任务，直接返回
        if not tasks_by_user:
            return

        # 为每个用户获取对应的认证服务（优先使用缓存）
        auth_manager = get_auth_manager()
        user_manager = get_user_manager()

        for user_id, tasks in tasks_by_user.items():
            auth_service = None

            try:
                # 统一使用 get_auth_service 方法获取认证服务
                # 传递正确的 user_id（包括 "global"）
                cache_key = user_id if user_id != "global" else None
                try:
                    auth_service = await auth_manager.get_auth_service(cache_key)
                except Exception as e:
                    # 只在第一次出现时记录警告
                    if not hasattr(self, f'_warned_{cache_key}'):
                        logger.warning(f"用户 {user_id} 无法创建认证服务: {e}")
                        setattr(self, f'_warned_{cache_key}', True)
                    auth_service = None

                if not auth_service:
                    # 将这些任务标记为失败（静默处理，不重复记录日志）
                    for task in tasks:
                        task_manager.update_task(
                            task.task_id,
                            status=TaskStatus.FAILED,
                            error_message="123云盘未配置"
                        )
                    continue

                # 监控该用户的所有任务
                for task_data in tasks:
                    try:
                        await self._monitor_single_task(task_manager, task_data, auth_service)
                    except Exception as e:
                        import traceback
                        error_detail = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
                        logger.error(f"监控任务 {task_data.task_id} 失败: {error_detail}")
                        logger.debug(f"异常堆栈: {traceback.format_exc()}")

            except Exception as e:
                import traceback
                error_detail = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
                logger.error(f"为用户 {user_id} 创建认证服务失败: {error_detail}")
                logger.debug(f"异常堆栈: {traceback.format_exc()}")

                # 将该用户的所有任务标记为失败
                for task in tasks:
                    task_manager.update_task(
                        task.task_id,
                        status=TaskStatus.FAILED,
                        error_message=f"认证服务错误: {error_detail}"
                    )

    async def _monitor_single_task(
        self,
        task_manager,
        task_data,
        auth_service: Pan123AuthService
    ):
        """监控单个任务"""
        task_id = task_data.task_id

        # 下载中状态
        if task_data.status == TaskStatus.DOWNLOADING.value and task_data.download_task_id:
            download_service = Pan123DownloadService(auth_service)

            try:
                progress_info = await download_service.get_download_progress(task_data.download_task_id)
                progress = progress_info["progress"]
                status_code = progress_info["status"]

                # 更新进度
                task_manager.update_task(task_id, progress=progress)

                # 检查是否下载完成
                if status_code == 2:  # 下载成功
                    logger.info(f"任务 {task_id} 下载完成，准备重命名")
                    _log_to_user(task_data, f"任务下载完成: {task_data.title}")

                    # 查找下载的文件
                    folder_service = Pan123FolderService(auth_service)
                    files = await folder_service.list_files(task_data.folder_id)

                    if files:
                        # 查找匹配的文件：优先查找未重命名的文件（格式：xxxxxx-xxxp.mp4）
                        # 并且是最近创建的文件（根据创建时间排序）
                        import re
                        from datetime import datetime

                        # 过滤出视频文件（格式：xxxxxx-xxxp.mp4），且不在回收站
                        video_files = []
                        for f in files:
                            if f.type == 0 and f.trashed == 0:  # 文件且不在回收站
                                # 检查文件名格式：数字-字母数字p.mp4（例如：110533-sc-1080p.mp4）
                                if re.match(r'^\d+-[a-zA-Z0-9\-]+p\.mp4$', f.filename):
                                    video_files.append(f)
                        
                        # 如果没有找到符合格式的文件，使用所有mp4文件（不在回收站）
                        if not video_files:
                            video_files = [f for f in files if f.type == 0 and f.trashed == 0 and f.filename.endswith('.mp4')]
                        
                        # 按创建时间排序，最新的在前
                        def parse_create_time(create_at_str):
                            try:
                                # 尝试解析时间字符串（格式可能是 "2025-01-02 23:46:24" 或 ISO格式）
                                if 'T' in create_at_str:
                                    return datetime.fromisoformat(create_at_str.replace('Z', '+00:00'))
                                else:
                                    return datetime.strptime(create_at_str, "%Y-%m-%d %H:%M:%S")
                            except:
                                return datetime.min
                        
                        video_files.sort(key=lambda f: parse_create_time(f.create_at), reverse=True)
                        
                        # 查找未被其他任务使用的文件
                        task_manager_instance = get_task_manager()
                        used_file_ids = {
                            t.file_id for t in task_manager_instance.list_tasks() 
                            if t.file_id is not None and t.task_id != task_id
                        }
                        
                        # 找到第一个未被使用的文件（优先选择未重命名的文件）
                        file = None
                        for f in video_files:
                            if f.file_id not in used_file_ids:
                                # 优先选择未重命名的文件（格式：xxxxxx-xxxp.mp4）
                                if re.match(r'^\d+-[a-zA-Z0-9\-]+p\.mp4$', f.filename):
                                    file = f
                                    break
                        
                        # 如果没找到未重命名的文件，使用第一个未被使用的文件
                        if file is None:
                            for f in video_files:
                                if f.file_id not in used_file_ids:
                                    file = f
                                    break
                        
                        # 如果所有文件都被使用，使用最新的文件（可能是重试的情况）
                        if file is None and video_files:
                            file = video_files[0]
                            logger.warning(f"所有文件都已被使用，使用最新文件: {file.filename}")
                        
                        if file:
                            task_manager.update_task(
                                task_id,
                                file_id=file.file_id,
                                status=TaskStatus.RENAMING
                            )
                            logger.info(f"找到文件: {file.filename}, ID: {file.file_id}, 将重命名为: {task_data.desired_name}")

                            # 记录用户日志：开始重命名
                            _log_to_user(task_data, f"开始重命名: {task_data.title}")

                        # 触发重命名
                        from services.rename_service import RenameService
                        rename_service = RenameService(auth_service)
                        success = await rename_service.execute_rename(
                            file_id=file.file_id,
                            desired_name=task_data.desired_name,
                            video_id=task_data.video_id
                        )

                        if success:
                            task_manager.update_task(
                                task_id,
                                status=TaskStatus.COMPLETED
                            )
                            logger.info(f"任务 {task_id} 重命名完成")
                            # 记录用户日志：重命名完成
                            _log_to_user(task_data, f"重命名完成: {task_data.title}")
                            _log_to_user(task_data, f"任务完成: {task_data.title}")

                            # 延迟5秒后自动推送封面
                            asyncio.create_task(auto_push_cover_after_delay(
                                task_data.video_id, 
                                task_data.user_id,
                                task_id,
                                delay_seconds=5
                            ))
                            logger.info(f"已安排自动推送封面任务：视频 {task_data.video_id}，延迟5秒")

                            # 任务完成后，更新该系列的不完善视频信息
                            try:
                                from services.database import get_database
                                db = get_database()
                                # 获取视频信息以获取系列名称
                                video_info = db.get_video(task_data.video_id)
                                if video_info and video_info.get("series_name"):
                                    # 更新该系列中标记为不完善的视频信息
                                    db.update_incomplete_video(video_info["series_name"], task_data.title)
                                    logger.debug(f"已更新系列 {video_info['series_name']} 的不完善视频信息")
                            except Exception as e:
                                logger.warning(f"更新不完善视频失败: {e}")
                        else:
                            task_manager.update_task(
                                task_id,
                                status=TaskStatus.FAILED,
                                error_message="重命名失败"
                            )
                            _log_to_user(task_data, f"任务重命名失败: {task_data.title}", "error")
                    else:
                        # 未找到文件，等待下次检查
                        logger.warning(f"任务 {task_id} 未找到下载的文件")

                elif status_code == 1:  # 下载失败
                    # 检查是否已经重试过
                    task_data = task_manager.get_task(task_id)
                    if task_data and task_data.retry_count < 1 and task_data.download_url:
                        # 重试一次
                        logger.info(f"任务 {task_id} 下载失败，尝试重试 (第 {task_data.retry_count + 1} 次)")
                        try:
                            # 重新创建下载任务
                            download_service = Pan123DownloadService(auth_service)
                            new_download_task_id = await download_service.create_download_task(
                                task_data.download_url,
                                task_data.folder_id
                            )
                            # 更新任务状态
                            task_manager.update_task(
                                task_id,
                                download_task_id=new_download_task_id,
                                status=TaskStatus.DOWNLOADING,
                                progress=0.0,
                                error_message=None,
                                retry_count=task_data.retry_count + 1
                            )
                            logger.info(f"任务 {task_id} 重试成功，新下载任务ID: {new_download_task_id}")
                        except Exception as retry_error:
                            logger.error(f"任务 {task_id} 重试失败: {retry_error}")
                            task_manager.update_task(
                                task_id,
                                status=TaskStatus.FAILED,
                                error_message=f"下载失败，重试也失败: {retry_error}",
                                retry_count=task_data.retry_count + 1
                            )
                    else:
                        # 已经重试过或无法重试，标记为失败
                        task_manager.update_task(
                            task_id,
                            status=TaskStatus.FAILED,
                            error_message="下载失败" + (f"（已重试 {task_data.retry_count} 次）" if task_data and task_data.retry_count > 0 else "")
                        )
                        error_msg = f"任务下载失败: {task_data.title}" + (f"（已重试 {task_data.retry_count} 次）" if task_data and task_data.retry_count > 0 else "")
                        logger.error(error_msg)
                        _log_to_user(task_data, error_msg, "error")

            except Exception as e:
                # 如果是未找到任务ID，直接删除该任务，不记录错误日志
                if "未找到任务ID" in str(e) or "not found task id" in str(e).lower():
                    task_manager.delete_task(task_id)
                else:
                    logger.error(f"查询下载进度失败: {e}")
    
    async def _cleanup_completed_tasks(self):
        """清理已完成超过1小时的任务"""
        try:
            task_manager = get_task_manager()
            now = datetime.now()
            one_hour_ago = now - timedelta(hours=1)
            
            completed_tasks = [
                task for task in task_manager.list_tasks()
                if task.status == TaskStatus.COMPLETED.value
            ]
            
            deleted_count = 0
            for task in completed_tasks:
                try:
                    # 解析更新时间
                    updated_at = datetime.fromisoformat(task.updated_at)
                    # 如果完成时间超过1小时，删除任务
                    if updated_at < one_hour_ago:
                        if task_manager.delete_task(task.task_id):
                            deleted_count += 1
                            # 使用debug级别，减少日志输出
                            logger.debug(f"自动删除已完成任务: {task.task_id} ({task.title})")
                except (ValueError, TypeError) as e:
                    logger.debug(f"解析任务时间失败: {task.task_id}, {e}")
                    continue
            
            if deleted_count > 0:
                # 只在有删除操作时输出一次汇总日志
                logger.info(f"自动清理了 {deleted_count} 个已完成任务")
        except Exception as e:
            logger.error(f"清理已完成任务时出错: {e}")


async def auto_push_cover_after_delay(video_id: str, user_id: str, task_id: str, delay_seconds: int = 5):
    """延迟后自动推送视频封面"""
    try:
        from pathlib import Path

        # 在延迟前先检查封面文件是否存在
        subdir = str(video_id)[:2] if len(str(video_id)) >= 2 else "00"
        cover_path = Path(__file__).parent.parent / "data" / "covers" / subdir / f"{video_id}.jpg"
        if not cover_path.exists():
            logger.info(f"自动推送封面跳过：视频 {video_id} 的封面文件不存在，等待手动推送")
            return

        logger.info(f"视频 {video_id} 的封面文件存在，等待 {delay_seconds} 秒后自动推送")
        _log_to_user(type('TaskData', (), {'user_id': user_id})(), f"检测到封面文件，{delay_seconds}秒后自动上传")
        await asyncio.sleep(delay_seconds)
        logger.info(f"开始自动推送视频 {video_id} 的封面")
        # 先获取视频信息用于日志
        from services.database import get_database
        from config import get_user_config
        from services.task_manager import get_task_manager
        import hashlib
        import aiofiles
        import aiohttp

        db = get_database()
        task_manager = get_task_manager()
        video = db.get_video(video_id)
        if not video:
            logger.warning(f"自动推送封面失败：视频 {video_id} 不存在")
            return
        _log_to_user(type('TaskData', (), {'user_id': user_id})(), f"开始上传封面: {video.get('title', video_id)}")

        # 再次检查封面文件（以防在延迟期间被删除）
        if not cover_path.exists():
            logger.warning(f"自动推送封面失败：封面文件在延迟期间被删除")
            return

        # 获取用户配置
        config = get_user_config(user_id)

        # 检查123云盘配置
        if not config.pan123.client_id and not config.pan123.client_secret and not config.pan123.access_token:
            logger.warning(f"自动推送封面失败：123云盘未配置 (user_id: {user_id})")
            return

        # 获取认证服务
        auth_manager = get_auth_manager()
        auth_service = await auth_manager.get_auth_service(user_id)

        # 读取封面文件
        async with aiofiles.open(cover_path, 'rb') as f:
            cover_data = await f.read()

        # 计算文件MD5
        file_md5 = hashlib.md5(cover_data).hexdigest()
        file_size = len(cover_data)

        # 生成文件名
        original_filename = video.get('rename_name', video.get('title', video_id))
        if '.' in original_filename:
            base_name = original_filename.rsplit('.', 1)[0]
        else:
            base_name = original_filename

        poster_filename = f"{base_name}-poster.jpg"
        poster_filename = poster_filename.replace('<', '_').replace('>', '_').replace(':', '_').replace('"', '_').replace('|', '_').replace('?', '_').replace('*', '_')
        if not poster_filename.strip():
            poster_filename = f"{video_id}-poster.jpg"
        if len(poster_filename) > 250:
            poster_filename = poster_filename[:250] + ".jpg"

        # 确定目标目录
        folder_service = Pan123FolderService(auth_service, user_id)
        root_dir_id = config.pan123.root_dir_id
        target_folder_id = None

        # 根据创建时间确定目录
        created_at = video.get('created_at', '')
        if created_at:
            try:
                if isinstance(created_at, str):
                    if 'T' in created_at:
                        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    else:
                        dt = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
                else:
                    dt = datetime.fromtimestamp(created_at)

                year = str(dt.year)
                month = str(dt.month).zfill(2)

                year_folder_id = await folder_service.find_folder(year, root_dir_id)
                if year_folder_id:
                    month_folder_id = await folder_service.find_folder(month, year_folder_id)
                    if month_folder_id:
                        target_folder_id = month_folder_id
                        logger.info(f"自动推送封面：根据创建时间确定目录 {year}/{month}")
                        _log_to_user(type('TaskData', (), {'user_id': user_id})(), f"上传目录: {year}/{month}")

            except Exception as e:
                logger.warning(f"自动推送封面：解析创建时间失败: {e}")

        if not target_folder_id:
            target_folder_id = root_dir_id
            logger.info(f"自动推送封面：使用根目录")
            _log_to_user(type('TaskData', (), {'user_id': user_id})(), f"上传目录: 根目录")

        # 上传封面
        upload_url = "https://openapi-upload.123242.com/upload/v2/file/single/create"

        # 更新任务状态为封面上传中
        task_manager.update_task(task_id, status=TaskStatus.COVER_UPLOADING)
        _log_to_user(type('TaskData', (), {'user_id': user_id})(), f"正在上传封面文件: {poster_filename}")

        data = aiohttp.FormData()
        data.add_field('parentFileID', str(target_folder_id))
        data.add_field('filename', poster_filename)
        data.add_field('etag', file_md5)
        data.add_field('size', str(file_size))
        data.add_field('file', cover_data, filename=poster_filename, content_type='image/jpeg')

        headers = {
            "Authorization": auth_service.get_auth_header(),
            "Platform": "open_platform"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(upload_url, data=data, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") == 0:
                        logger.info(f"自动推送封面成功：{poster_filename}")
                        # 封面上传成功后，状态保持为已完成
                        task_manager.update_task(task_id, status=TaskStatus.COMPLETED)
                        # 记录用户日志
                        _log_to_user(type('TaskData', (), {'user_id': user_id})(), f"封面上传成功: {poster_filename}")
                    else:
                        logger.warning(f"自动推送封面失败：{result.get('message')}")
                        task_manager.update_task(task_id, status=TaskStatus.COVER_UPLOAD_FAILED, error_message=f"封面上传失败: {result.get('message')}")
                        # 记录用户日志
                        _log_to_user(type('TaskData', (), {'user_id': user_id})(), f"封面上传失败: {result.get('message')}", "error")
                else:
                    response_text = await response.text()
                    logger.error(f"自动推送封面失败：HTTP {response.status} - {response_text}")
                    task_manager.update_task(task_id, status=TaskStatus.COVER_UPLOAD_FAILED, error_message=f"封面上传失败: HTTP {response.status}")
                    # 记录用户日志
                    _log_to_user(type('TaskData', (), {'user_id': user_id})(), f"封面上传失败: HTTP {response.status}", "error")

    except Exception as e:
        logger.error(f"自动推送封面异常：{e}")
