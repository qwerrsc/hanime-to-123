"""
任务管理服务
负责任务的生命周期管理和数据持久化
"""
import uuid
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from dataclasses import dataclass
from loguru import logger

from api.models import TaskStatus, TaskInfo
from services.pan123_service import (
    Pan123AuthService,
    Pan123FolderService,
    Pan123DownloadService
)
from services.database import get_database


@dataclass
class TaskData:
    """任务数据存储模型"""
    task_id: str
    video_id: str
    title: str
    folder_id: int
    folder_name: str
    download_task_id: Optional[int]
    status: str
    progress: float
    file_id: Optional[int]
    desired_name: Optional[str]
    created_at: str
    updated_at: str
    error_message: Optional[str]
    download_url: Optional[str] = None  # 下载链接，用于重试
    retry_count: int = 0  # 重试次数
    user_id: Optional[str] = None  # 用户ID，用于多用户支持

    def to_model(self) -> TaskInfo:
        """转换为API模型"""
        return TaskInfo(
            task_id=self.task_id,
            video_id=self.video_id,
            title=self.title,
            folder_id=self.folder_id,
            folder_name=self.folder_name,
            download_task_id=self.download_task_id,
            status=TaskStatus(self.status),
            progress=self.progress,
            file_id=self.file_id,
            desired_name=self.desired_name,
            created_at=datetime.fromisoformat(self.created_at),
            updated_at=datetime.fromisoformat(self.updated_at),
            error_message=self.error_message
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'TaskData':
        """从字典创建"""
        return cls(
            task_id=data["task_id"],
            video_id=data["video_id"],
            title=data["title"],
            folder_id=data["folder_id"],
            folder_name=data["folder_name"],
            download_task_id=data.get("download_task_id"),
            status=data["status"],
            progress=data.get("progress", 0.0),
            file_id=data.get("file_id"),
            desired_name=data.get("desired_name"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            error_message=data.get("error_message"),
            download_url=data.get("download_url"),
            retry_count=data.get("retry_count", 0),
            user_id=data.get("user_id")
        )


class TaskManager:
    """任务管理器"""

    def __init__(self):
        self.db = get_database()
        self._load_cache()

    def _load_cache(self):
        """从数据库加载任务到缓存"""
        self.tasks_cache = {}
        try:
            task_dicts = self.db.get_all_tasks()
            self.tasks_cache = {
                task_data["task_id"]: TaskData.from_dict(task_data)
                for task_data in task_dicts
            }
            logger.info(f"加载了 {len(self.tasks_cache)} 个任务")
        except Exception as e:
            logger.error(f"加载任务失败: {e}")
            self.tasks_cache = {}

    async def create_task(
        self,
        video_id: str,
        title: str,
        download_url: str,
        folder_name: str,
        parent_dir_id: int,
        auth_service: Pan123AuthService,
        desired_name: Optional[str] = None,
        user_id: Optional[str] = None,
        skip_folder_creation: bool = False
    ) -> TaskData:
        """创建新任务"""
        task_id = str(uuid.uuid4())

        # 创建文件夹（如果已存在则复用），除非指定跳过
        if not skip_folder_creation:
            folder_service = Pan123FolderService(auth_service, user_id or "global")
            folder_id = await folder_service.create_folder(folder_name, parent_dir_id, check_exists=True)
        else:
            # 跳过文件夹创建，直接使用传入的 parent_dir_id 作为文件夹ID
            folder_id = parent_dir_id

        # 创建离线下载任务
        download_service = Pan123DownloadService(auth_service)

        # 尝试创建下载任务，如果失败（文件夹 ID 失效），则重新创建文件夹
        try:
            download_task_id = await download_service.create_download_task(
                download_url,
                folder_id
            )
        except Exception as e:
            error_msg = str(e) if str(e) else ""
            if "指定目录ID文件不存在" in error_msg or "目录不存在" in error_msg:
                # 文件夹 ID 失效，重新创建文件夹（不检查是否存在，强制创建新的）
                logger.warning(f"文件夹 ID {folder_id} 已失效，尝试重新创建文件夹: {folder_name}")
                try:
                    folder_service = Pan123FolderService(auth_service, user_id or "global")
                    folder_id = await folder_service.create_folder(folder_name, parent_dir_id, check_exists=False)
                    logger.info(f"重新创建文件夹成功: {folder_name}, 新 ID: {folder_id}")
                    # 再次尝试创建下载任务
                    download_task_id = await download_service.create_download_task(
                        download_url,
                        folder_id
                    )
                except Exception as retry_error:
                    logger.error(f"重新创建文件夹后仍然失败: {retry_error}")
                    raise
            else:
                # 其他错误，直接抛出
                raise

        # 创建任务记录
        task = TaskData(
            task_id=task_id,
            video_id=video_id,
            title=title,
            folder_id=folder_id,
            folder_name=folder_name,
            download_task_id=download_task_id,
            status=TaskStatus.DOWNLOADING.value,
            progress=0.0,
            file_id=None,
            desired_name=desired_name if desired_name else title,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            error_message=None,
            download_url=download_url,
            retry_count=0,
            user_id=user_id
        )

        self.tasks_cache[task_id] = task

        # 保存到数据库
        task_dict = {
            "task_id": task.task_id,
            "video_id": task.video_id,
            "title": task.title,
            "folder_id": task.folder_id,
            "folder_name": task.folder_name,
            "download_task_id": task.download_task_id,
            "status": task.status,
            "progress": task.progress,
            "file_id": task.file_id,
            "desired_name": task.desired_name,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "error_message": task.error_message,
            "download_url": task.download_url,
            "retry_count": task.retry_count,
            "user_id": task.user_id
        }
        self.db.create_task(task_dict)

        logger.info(f"创建任务成功: {task_id}, 文件夹ID: {folder_id}")
        return task

    def get_task(self, task_id: str) -> Optional[TaskData]:
        """获取任务"""
        return self.tasks_cache.get(task_id)

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[float] = None,
        file_id: Optional[int] = None,
        error_message: Optional[str] = None,
        download_task_id: Optional[int] = None,
        retry_count: Optional[int] = None
    ) -> bool:
        """更新任务状态"""
        task = self.tasks_cache.get(task_id)
        if not task:
            return False

        if status:
            task.status = status.value
        if progress is not None:
            task.progress = progress
        if file_id is not None:
            task.file_id = file_id
        if error_message is not None:
            task.error_message = error_message
        if download_task_id is not None:
            task.download_task_id = download_task_id
        if retry_count is not None:
            task.retry_count = retry_count

        task.updated_at = datetime.now().isoformat()

        # 更新数据库
        update_data = {"updated_at": task.updated_at}
        if status:
            update_data["status"] = task.status
        if progress is not None:
            update_data["progress"] = task.progress
        if file_id is not None:
            update_data["file_id"] = task.file_id
        if error_message is not None:
            update_data["error_message"] = task.error_message
        if download_task_id is not None:
            update_data["download_task_id"] = task.download_task_id
        if retry_count is not None:
            update_data["retry_count"] = task.retry_count

        self.db.update_task(task_id, update_data)
        return True

    def cancel_task(self, task_id: str) -> bool:
        """取消任务（标记为失败）"""
        return self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            error_message="用户取消"
        )

    def delete_task(self, task_id: str) -> bool:
        """删除任务记录"""
        if task_id in self.tasks_cache:
            del self.tasks_cache[task_id]
            self.db.delete_task(task_id)
            return True
        return False

    def delete_tasks_by_status(self, status: str, user_id: Optional[str] = None) -> int:
        """根据状态批量删除任务"""
        # 从数据库删除
        deleted_count = self.db.delete_tasks_by_status(status, user_id)
        # 清理缓存
        self._load_cache()
        return deleted_count

    def delete_all_tasks(self, user_id: Optional[str] = None) -> int:
        """删除所有任务"""
        # 从数据库删除
        deleted_count = self.db.delete_all_tasks(user_id)
        # 清理缓存
        self._load_cache()
        return deleted_count

    def list_tasks(self, status_filter: Optional[str] = None, user_id: Optional[str] = None) -> List[TaskData]:
        """列出任务"""
        # 从数据库查询而不是使用缓存
        task_dicts = self.db.get_all_tasks(status_filter, user_id)
        tasks = [TaskData.from_dict(task_data) for task_data in task_dicts]
        return tasks

    def get_task_statistics(self, user_id: Optional[str] = None) -> dict:
        """获取任务统计"""
        return self.db.get_task_statistics(user_id)


# 全局任务管理器实例
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """获取任务管理器单例"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
