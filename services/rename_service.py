"""
文件重命名服务
"""
import asyncio
from typing import Tuple, Optional
from loguru import logger

from services.pan123_service import (
    Pan123AuthService,
    Pan123FileService
)


class RenameService:
    """文件重命名服务"""

    def __init__(self, auth_service: Pan123AuthService):
        self.auth = auth_service
        self.file_service = Pan123FileService(auth_service)

    async def execute_rename(
        self,
        file_id: int,
        desired_name: str,
        video_id: Optional[str] = None
    ) -> bool:
        """执行文件重命名"""
        try:
            # 清理文件名
            clean_name = self.sanitize_filename(desired_name)

            # 添加扩展名
            if not clean_name.endswith('.mp4'):
                clean_name += '.mp4'

            # 如果有video_id，尝试提取原文件的后缀
            # 这里简化处理，直接使用.mp4

            # 执行重命名
            success = await self.file_service.rename_file(file_id, clean_name)

            if success:
                logger.info(f"文件重命名成功: {file_id} -> {clean_name}")
            else:
                logger.error(f"文件重命名失败: {file_id}")

            return success

        except Exception as e:
            logger.error(f"重命名文件时出错: {e}")
            return False

    def sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符"""
        # 移除Windows不允许的字符
        illegal_chars = '<>:"/\\|?*\x00-\x1f'
        for char in illegal_chars:
            filename = filename.replace(char, '_')

        # 移除前后空格
        filename = filename.strip()

        # 如果为空，使用默认名称
        if not filename:
            filename = "未命名视频"

        return filename

    async def wait_for_download_completion(
        self,
        download_task_id: int,
        timeout: int = 3600
    ) -> bool:
        """等待下载完成"""
        from services.pan123_service import Pan123DownloadService

        download_service = Pan123DownloadService(self.auth)
        elapsed = 0
        interval = 30  # 30秒检查一次

        while elapsed < timeout:
            try:
                progress_info = await download_service.get_download_progress(download_task_id)
                status_code = progress_info["status"]

                if status_code == 2:  # 下载成功
                    return True
                elif status_code == 1:  # 下载失败
                    return False

                await asyncio.sleep(interval)
                elapsed += interval

            except Exception as e:
                logger.error(f"检查下载状态失败: {e}")
                await asyncio.sleep(interval)
                elapsed += interval

        return False
