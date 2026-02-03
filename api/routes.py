"""
API 路由定义
"""
import json
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from loguru import logger

from api.models import (
    VideoSubmitRequest,
    VideoSubmitResponse,
    TaskInfo,
    TaskStatus,
    TaskStatusResponse,
    TaskListResponse,
    TaskStatisticsResponse,
    HealthResponse,
    ErrorResponse,
    FolderCheckRequest,
    FolderCheckResponse,
    FolderFileInfo,
    Pan123TokenResponse,
    VideoInfo,
    VideoCreateRequest,
    VideoListResponse
)
from services.task_manager import get_task_manager, TaskManager
from services.pan123_service import Pan123AuthService, Pan123FolderService, Pan123AndroidFolderService, Pan123DownloadService
from services.auth_manager import get_auth_manager
from services.user_manager import get_user_manager
from config import get_config, get_config_manager, get_user_config
from api.auth import get_user_id, get_webui_user_id, require_user_id_from_any_source, get_user_id_from_any_source, require_webui_auth
import re
import aiohttp
import asyncio
from datetime import datetime

router = APIRouter(prefix="/api")


async def download_cover_with_retry(cover_url: str, save_path: str, max_retries: int = 3) -> Optional[str]:
    """
    带重试机制的封面下载函数

    Args:
        cover_url: 封面URL
        save_path: 保存路径
        max_retries: 最大重试次数（默认3次）

    Returns:
        下载成功返回保存路径，失败返回None
    """
    import os
    from pathlib import Path

    for attempt in range(max_retries):
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
                async with session.get(cover_url) as response:
                    if response.status == 200:
                        content = await response.read()
                        # 确保目录存在
                        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                        with open(save_path, 'wb') as f:
                            f.write(content)
                        logger.info(f"封面下载成功: {save_path} (尝试 {attempt + 1}/{max_retries})")
                        return save_path
                    else:
                        logger.warning(f"封面下载失败: HTTP {response.status} (尝试 {attempt + 1}/{max_retries})")
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            logger.warning(f"封面下载失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                # 等待一段时间后重试
                await asyncio.sleep(2 ** attempt)  # 指数退避: 1s, 2s, 4s
            else:
                logger.error(f"封面下载失败，已达到最大重试次数: {cover_url}")

    return None


async def delete_cloud_incomplete_video(
    series_name: str,
    video_title: str,
    auth_service: Pan123AuthService,
    user_id: str = "global"
) -> bool:
    """
    删除云盘中对应的不完善视频
    只有当完善版本和不完善版本都存在于云盘时才删除不完善版本
    """
    try:
        folder_service = Pan123AndroidFolderService(auth_service)
        
        # 查找文件夹
        folder_id = await folder_service.find_folder(series_name, 0)
        if not folder_id:
            return False
        
        # 获取文件夹中的所有文件
        files = await folder_service.list_files(folder_id)
        
        # 提取基础标题（去除序号、[中字後補]等）
        import re as regex_module
        base_title = regex_module.sub(r'\s+\d+$', '', video_title).strip()
        base_title = regex_module.sub(r'\s*\[中字後補\]\s*', '', base_title).strip()
        
        # 查找完善版本和不完善版本
        complete_file_id = None
        incomplete_file_ids = []
        
        for file in files:
            if file.type != 0 or file.trashed != 0:
                continue
            
            filename_no_ext = file.filename.rsplit('.', 1)[0] if '.' in file.filename else file.filename
            
            # 检查是否是完善版本
            if base_title in filename_no_ext and "[中字後補]" not in filename_no_ext:
                complete_file_id = file.file_id
            # 检查是否是不完善版本
            elif base_title in filename_no_ext and "[中字後補]" in filename_no_ext:
                incomplete_file_ids.append(file.file_id)
        
        # 只有当完善版本存在时，才删除不完善版本
        if complete_file_id and incomplete_file_ids:
            # 批量删除不完善文件
            success = await folder_service.trash_files(incomplete_file_ids)
            if success:
                logger.info(f"已删除云盘中 {len(incomplete_file_ids)} 个不完善视频: {video_title}")
            return success
        
        return False
    except Exception as e:
        logger.error(f"删除云盘不完善视频失败: {e}")
        return False


@router.post("/video/submit", response_model=VideoSubmitResponse)
async def submit_video(request: VideoSubmitRequest, user_id: str = Depends(require_user_id_from_any_source)):
    """提交视频下载任务"""
    try:
        # 使用用户配置
        config = get_user_config(user_id)

        # 检查123云盘配置（支持两种认证方式：Client ID/Secret 或 Access Token）
        if not config.pan123.client_id and not config.pan123.client_secret and not config.pan123.access_token:
            logger.warning("123云盘未配置")
            raise HTTPException(status_code=400, detail="123云盘未配置，请先配置 Client ID/Secret 或使用账号密码登录")

        # 检查download_url是否提供
        if not request.download_url or not request.download_url.strip():
            logger.warning(f"download_url 为空，video_id: {request.video_id}, title: {request.title}")
            raise HTTPException(
                status_code=400,
                detail="download_url 是必需的。系列下载时请确保为每个视频提供下载链接"
            )

        # 检查是否提供了月份文件夹（新逻辑必需）
        if not request.month_folder:
            logger.warning(f"month_folder 未提供，video_id: {request.video_id}")
            raise HTTPException(
                status_code=400,
                detail="month_folder 是必需的"
            )

        # 获取认证服务（复用实例，避免重复获取token）
        auth_manager = get_auth_manager()
        auth_service = await auth_manager.get_auth_service(user_id)

        # 创建年月文件夹结构（使用 Android 客户端 API）
        folder_service = Pan123AndroidFolderService(auth_service)
        root_dir_id = request.parent_dir_id or config.pan123.root_dir_id

        # 1. 查找或创建年份文件夹
        year_folder_id = await folder_service.create_folder(request.folder_name, root_dir_id, check_exists=True)
        logger.info(f"年份文件夹: {request.folder_name}, ID: {year_folder_id}")

        # 2. 查找或创建月份文件夹
        month_folder_id = await folder_service.create_folder(request.month_folder, year_folder_id, check_exists=True)
        logger.info(f"月份文件夹: {request.month_folder}, ID: {month_folder_id}")

        # 如果提供了 rename_name，使用它作为 desired_name，否则使用 title
        desired_name = request.rename_name if request.rename_name else request.title

        # 保存 rename_name 到数据库（如果提供了）
        if request.rename_name:
            try:
                from services.database import get_database
                db = get_database()
                # 检查视频是否存在
                video = db.get_video(request.video_id)
                now_iso = datetime.now().isoformat()
                if video:
                    # 更新视频的 rename_name
                    video.update({
                        "rename_name": request.rename_name,
                        "updated_at": now_iso
                    })
                    db.create_or_update_video(video)
                    logger.info(f"更新视频重命名: {request.video_id} -> {request.rename_name}")
                else:
                    # 如果视频不存在，插入一条最小信息记录，保存 rename_name
                    video_data = {
                        "video_id": request.video_id,
                        "title": request.title,
                        "series_name": None,
                        "cover_url": None,
                        "duration": None,
                        "local_url": request.download_url,
                        "created_at": now_iso,
                        "updated_at": now_iso,
                        "user_id": user_id,
                        "rename_name": request.rename_name
                    }
                    db.create_or_update_video(video_data)
                    logger.info(f"插入视频并保存重命名: {request.video_id} -> {request.rename_name}")
            except Exception as e:
                logger.warning(f"保存重命名文件名失败: {e}")

        # 记录用户日志：开始创建任务
        from api.user_logger import add_user_log_handler
        add_user_log_handler(user_id)
        user_logger = logger.bind(user_id=user_id)
        user_logger.info(f"创建下载任务: {request.title}")

        # 创建任务（直接在月份文件夹下下载）
        task_manager = get_task_manager()
        task = await task_manager.create_task(
            video_id=request.video_id,
            title=request.title,  # 完整标题（用于记录）
            download_url=request.download_url,
            folder_name=request.month_folder,  # 月份文件夹名称
            parent_dir_id=month_folder_id,  # 使用月份文件夹ID
            auth_service=auth_service,
            desired_name=desired_name,  # 用于重命名的文件名
            user_id=user_id,
            skip_folder_creation=True  # 跳过create_task中的文件夹创建，因为已经在这里创建了
        )

        # 记录用户日志：任务创建成功
        user_logger.info(f"创建任务成功: {task.task_id}, 文件夹ID: {task.folder_id}")

        # 记录用户日志：下载任务创建成功
        user_logger.info(f"创建离线下载任务成功: {request.download_url}, 任务ID: {task.download_task_id}")

        # 记录用户日志
        try:
            user_logger.info(f"提交视频任务: {request.title}, 任务ID: {task.task_id}")
            logger.info(f"用户日志已记录: user_id={user_id}, task_id={task.task_id}")
        except Exception as e:
            logger.warning(f"记录用户任务日志失败: {e}")

        return VideoSubmitResponse(
            success=True,
            task_id=task.task_id,
            folder_id=task.folder_id,
            download_task_id=task.download_task_id,
            message="任务创建成功"
        )

    except HTTPException as e:
        # HTTPException 应该直接抛出，但先记录日志
        logger.warning(f"请求验证失败: status_code={e.status_code}, detail={e.detail}")
        raise
    except Exception as e:
        import traceback
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else repr(e)
        error_detail = f"{error_type}: {error_msg}"

        # 检查是否是免费次数用完的错误
        if "免费次数" in error_msg or "VIP会员" in error_msg:
            # 记录警告级别日志，不记录错误堆栈
            logger.warning(f"免费次数已用完: {request.title}, 用户ID: {user_id}")
            # 返回友好的提示
            raise HTTPException(
                status_code=429,
                detail="免费次数已用完，开通VIP会员即可继续使用"
            )

        logger.error(f"提交视频任务失败: {error_detail}")
        logger.debug(f"异常堆栈:\n{traceback.format_exc()}")

        # 记录用户错误日志
        try:
            from api.user_logger import add_user_log_handler
            add_user_log_handler(user_id)
            user_logger = logger.bind(user_id=user_id)
            user_logger.error(f"提交视频任务失败: {request.title}, 错误: {error_detail}")
        except Exception:
            pass

        raise HTTPException(status_code=500, detail=error_detail)


@router.get("/task/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """获取任务状态"""
    try:
        task_manager = get_task_manager()
        task = task_manager.get_task(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        task_model = task.to_model()

        return TaskStatusResponse(
            task_id=task_id,
            status=task_model.status,
            progress=task_model.progress,
            message=f"{task_model.status.value}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    status: Optional[str] = "all",
    user_id: str = Depends(require_user_id_from_any_source)
):
    """获取当前用户的任务"""
    try:
        task_manager = get_task_manager()
        tasks = task_manager.list_tasks(status_filter=status, user_id=user_id)

        return TaskListResponse(
            tasks=[task.to_model() for task in tasks],
            total=len(tasks)
        )

    except Exception as e:
        logger.error(f"获取任务列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/task/{task_id}")
async def delete_task(task_id: str, user_id: str = Depends(require_user_id_from_any_source)):
    """删除任务"""
    try:
        task_manager = get_task_manager()
        task = task_manager.get_task(task_id)

        # 检查任务是否存在
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 检查任务是否属于当前用户
        if task.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权删除此任务")

        success = task_manager.delete_task(task_id)

        return {"success": True, "message": "任务已删除"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/completed")
async def delete_completed_tasks(user_id: str = Depends(require_user_id_from_any_source)):
    """删除当前用户所有已完成的任务"""
    try:
        task_manager = get_task_manager()
        deleted_count = task_manager.delete_tasks_by_status("completed", user_id=user_id)

        if deleted_count == 0:
            return {"success": True, "message": "没有已完成的任务", "deleted": 0}

        return {"success": True, "message": f"已删除 {deleted_count} 个已完成的任务", "deleted": deleted_count}

    except Exception as e:
        logger.error(f"批量删除已完成任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/all")
async def delete_all_tasks(user_id: str = Depends(require_user_id_from_any_source)):
    """删除当前用户的所有任务"""
    try:
        task_manager = get_task_manager()
        deleted_count = task_manager.delete_all_tasks(user_id=user_id)

        if deleted_count == 0:
            return {"success": True, "message": "没有任务", "deleted": 0}

        return {"success": True, "message": f"已删除所有 {deleted_count} 个任务", "deleted": deleted_count}

    except Exception as e:
        logger.error(f"批量删除所有任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/task/{task_id}/cancel")
async def cancel_task(task_id: str, user_id: str = Depends(require_user_id_from_any_source)):
    """取消任务"""
    try:
        task_manager = get_task_manager()
        task = task_manager.get_task(task_id)

        # 检查任务是否存在
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 检查任务是否属于当前用户
        if task.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权操作此任务")

        success = task_manager.cancel_task(task_id)

        return {"success": True, "message": "任务已取消"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/task/{task_id}/retry")
async def retry_task(task_id: str, user_id: str = Depends(require_user_id_from_any_source)):
    """重试失败的任务"""
    try:
        # 使用用户配置
        config = get_user_config(user_id)

        # 检查123云盘配置（支持两种认证方式：Client ID/Secret 或 Access Token）
        if not config.pan123.client_id and not config.pan123.client_secret and not config.pan123.access_token:
            logger.warning("123云盘未配置")
            raise HTTPException(status_code=400, detail="123云盘未配置，请先配置 Client ID/Secret 或使用账号密码登录")

        # 获取认证服务
        auth_manager = get_auth_manager()
        auth_service = await auth_manager.get_auth_service(user_id)

        # 获取任务管理器
        task_manager = get_task_manager()
        task = task_manager.get_task(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 检查任务是否属于当前用户
        if task.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权操作此任务")

        # 检查任务状态，只有失败的任务可以重试
        if task.status != TaskStatus.FAILED:
            raise HTTPException(status_code=400, detail="只有失败的任务可以重试")

        # 检查是否有下载链接
        if not task.download_url:
            raise HTTPException(status_code=400, detail="任务没有下载链接，无法重试")

        # 重新创建下载任务
        download_service = Pan123DownloadService(auth_service)
        download_task_id = await download_service.create_download_task(
            url=task.download_url,
            dir_id=task.folder_id
        )

        # 更新任务状态
        task_manager.update_task(
            task_id,
            download_task_id=download_task_id,
            status=TaskStatus.DOWNLOADING,
            progress=0.0,
            error_message=None
        )

        logger.info(f"重试任务成功: {task_id}, 新下载任务ID: {download_task_id}")

        return {"success": True, "message": "任务已重新推送", "download_task_id": download_task_id}

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else repr(e)
        error_detail = f"{error_type}: {error_msg}"
        logger.error(f"重试任务失败: {error_detail}")
        logger.debug(f"异常堆栈:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_detail)


@router.get("/statistics", response_model=TaskStatisticsResponse)
async def get_statistics(user_id: str = Depends(require_user_id_from_any_source)):
    """获取当前用户的任务统计"""
    try:
        task_manager = get_task_manager()
        stats = task_manager.get_task_statistics(user_id=user_id)

        return TaskStatisticsResponse(**stats)

    except Exception as e:
        logger.error(f"获取任务统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return HealthResponse(status="ok", version="1.0.0")


@router.get("/.well-known/appspecific/com.chrome.devtools.json")
async def devtools_json():
    """Chrome DevTools 自动请求，返回空对象避免 404"""
    return {"version": "1.0"}


@router.post("/folder/check", response_model=FolderCheckResponse)
async def check_folder(request: FolderCheckRequest, user_id: str = Depends(require_user_id_from_any_source)):
    """检查文件夹是否存在，以及文件列表"""
    try:
        # 使用用户配置
        config = get_user_config(user_id)

        # 检查123云盘配置（支持两种认证方式：Client ID/Secret 或 Access Token）
        if not config.pan123.client_id and not config.pan123.client_secret and not config.pan123.access_token:
            raise HTTPException(status_code=400, detail="123云盘未配置，请先配置 Client ID/Secret 或使用账号密码登录")

        # 获取认证服务（复用实例，避免重复获取token）
        auth_manager = get_auth_manager()
        auth_service = await auth_manager.get_auth_service(user_id)

        # 查找文件夹（去除 [中字後補] 标记，确保文件夹名称一致）
        import re as regex_module
        folder_name_clean = regex_module.sub(r'\[中字後補\]\s*', '', request.folder_name).strip()

        folder_service = Pan123AndroidFolderService(auth_service)
        parent_dir_id = request.parent_dir_id or config.pan123.root_dir_id

        # 记录用户日志：开始查找文件夹
        from api.user_logger import add_user_log_handler
        add_user_log_handler(user_id)
        user_logger = logger.bind(user_id=user_id)
        user_logger.info(f"查找文件夹: {folder_name_clean}")

        folder_id = await folder_service.find_folder(folder_name_clean, parent_dir_id)

        response_data = {
            "folder_exists": folder_id is not None,
            "folder_id": folder_id,
            "files": [],
            "video_exists": False,
            "missing_episodes": [],
            "message": None,
            "root_dir_id": config.pan123.root_dir_id
        }

        # 如果文件夹存在，获取文件列表
        if folder_id:
            # 记录用户日志：找到文件夹
            user_logger.info(f"找到已存在的文件夹: {folder_name_clean}, ID: {folder_id}")

            files = await folder_service.list_files(folder_id)
            files = await folder_service.list_files(folder_id)

            # 转换为响应模型
            file_list = []
            for file in files:
                # 只返回文件（不包括子文件夹）且不在回收站的文件
                if file.type == 0 and file.trashed == 0:
                    file_list.append(FolderFileInfo(
                        file_id=file.file_id,
                        filename=file.filename,
                        size=file.size,
                        category=file.category
                    ))
            
            response_data["files"] = file_list

            # 检查视频是否已存在（包括重命名后的文件）
            if request.video_title:
                # 清理视频标题（移除非法字符）
                import re as regex_module
                video_title_clean = regex_module.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', request.video_title).strip()
                # 去除 [中字後補] 标记用于匹配
                video_title_for_match = regex_module.sub(r'\[中字後補\]\s*', '', video_title_clean).strip()
                
                # 检查文件名是否包含视频标题（去掉扩展名）
                for file in file_list:
                    filename_no_ext = file.filename.rsplit('.', 1)[0] if '.' in file.filename else file.filename
                    # 去除 [中字後補] 标记用于匹配
                    filename_for_match = regex_module.sub(r'\[中字後補\]\s*', '', filename_no_ext).strip()

                    # 方法1: 完全匹配（去除空格和特殊字符后）
                    video_title_normalized = regex_module.sub(r'[\s_\-]', '', video_title_for_match).lower()
                    filename_normalized = regex_module.sub(r'[\s_\-]', '', filename_for_match).lower()

                    # 完全匹配才认为是同一个视频
                    if video_title_normalized == filename_normalized:
                        response_data["video_exists"] = True
                        response_data["message"] = f"视频已存在: {file.filename}"
                        break
                    
                    # 方法3: 检查文件名是否包含视频标题的关键部分（去除序号后）
                    # 例如：视频标题 "甜蜜惡作劇 1"，文件名可能是 "甜蜜惡作劇 1.mp4" 或已重命名为 "甜蜜惡作劇 1"
                    # 提取系列名称部分进行匹配
                    series_name_from_title = regex_module.sub(r'\s+\d+$', '', video_title_for_match).strip()
                    series_name_from_file = regex_module.sub(r'\s+\d+$', '', filename_for_match).strip()
                    if series_name_from_title and series_name_from_file:
                        series_title_norm = regex_module.sub(r'[\s_\-]', '', series_name_from_title).lower()
                        series_file_norm = regex_module.sub(r'[\s_\-]', '', series_name_from_file).lower()
                        if series_title_norm == series_file_norm:
                            # 进一步检查序号是否匹配
                            title_num_match = regex_module.search(r'(\d+)$', video_title_for_match)
                            file_num_match = regex_module.search(r'(\d+)$', filename_for_match)
                            if title_num_match and file_num_match:
                                if title_num_match.group(1) == file_num_match.group(1):
                                    response_data["video_exists"] = True
                                    response_data["message"] = f"视频已存在（已重命名）: {file.filename}"
                                    break

            # 如果是系列视频，检查缺少的集数
            if request.series_titles and len(request.series_titles) > 0:
                existing_titles = {file.filename.rsplit('.', 1)[0] if '.' in file.filename else file.filename
                                  for file in file_list}

                missing = []
                import re as regex_module
                for series_title in request.series_titles:
                    series_title_clean = regex_module.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', series_title).strip()
                    # 去除 [中字後補] 标记进行比较（文件名可能包含或不包含）
                    series_title_for_match = regex_module.sub(r'\[中字後補\]\s*', '', series_title_clean).strip()

                    # 检查是否存在匹配的文件（使用更精确的匹配）
                    found = False
                    # 去除所有空格和特殊字符后进行完全匹配
                    series_title_normalized = regex_module.sub(r'[\s_\-]', '', series_title_for_match).lower()

                    for existing_title in existing_titles:
                        existing_title_for_match = regex_module.sub(r'\[中字後補\]\s*', '', existing_title).strip()
                        # 去除所有空格和特殊字符
                        existing_title_normalized = regex_module.sub(r'[\s_\-]', '', existing_title_for_match).lower()

                        # 使用完全匹配（更严格）
                        if series_title_normalized == existing_title_normalized:
                            found = True
                            break

                        # 如果完全匹配失败，尝试检查序号是否匹配
                        # 例如：视频标题 "甜蜜惡作劇 1"，文件名可能是 "甜蜜惡作劇 1"
                        series_name_from_title = regex_module.sub(r'\s+\d+$', '', series_title_for_match).strip()
                        series_name_from_file = regex_module.sub(r'\s+\d+$', '', existing_title_for_match).strip()

                        if series_name_from_title and series_name_from_file:
                            series_name_norm = regex_module.sub(r'[\s_\-]', '', series_name_from_title).lower()
                            series_file_norm = regex_module.sub(r'[\s_\-]', '', series_name_from_file).lower()

                            if series_name_norm == series_file_norm:
                                # 进一步检查序号是否匹配
                                title_num_match = regex_module.search(r'(\d+)$', series_title_for_match)
                                file_num_match = regex_module.search(r'(\d+)$', existing_title_for_match)
                                if title_num_match and file_num_match:
                                    if title_num_match.group(1) == file_num_match.group(1):
                                        found = True
                                        break

                    if not found:
                        missing.append(series_title)

                response_data["missing_episodes"] = missing

                if missing:
                    response_data["message"] = f"缺少 {len(missing)} 集: {', '.join(missing[:3])}" + \
                                             (f" 等" if len(missing) > 3 else "")
                else:
                    response_data["message"] = "所有集数都已存在"
        else:
            response_data["message"] = "文件夹不存在"
            # 提示可以手动选择文件夹
            response_data["suggest_manual_select"] = True

        return FolderCheckResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else repr(e)
        error_detail = f"{error_type}: {error_msg}"
        logger.error(f"检查文件夹失败: {error_detail}")
        logger.debug(f"异常堆栈:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_detail)



# 配置API
class ConfigResponse(BaseModel):
    """配置响应模型"""
    server: Dict[str, Any]
    pan123: Dict[str, Any]
    monitoring: Dict[str, Any]


class ConfigUpdateRequest(BaseModel):
    """配置更新请求模型"""
    server: Optional[Dict[str, Any]] = None  # 可选，客户端可能不发送此配置
    pan123: Optional[Dict[str, Any]] = None
    monitoring: Optional[Dict[str, Any]] = None


@router.get("/config/public")
async def get_config_public(request: Request):
    """获取配置（公开版本，用于folder-picker等不需要登录的场景）"""
    try:
        from api.auth import get_webui_user
        from services.user_manager import get_user_manager

        user = await get_webui_user(request, Response())
        user_id = None

        if user:
            user_id = user.get('user_id')

        user_manager = get_user_manager()
        config = get_config()

        # 如果有用户ID，尝试获取用户配置
        if user_id:
            user_config = user_manager.get_user_config(user_id)
            if "pan123" in user_config:
                pan123_root_dir = user_config["pan123"].get("root_dir_id", config.pan123.root_dir_id)
                from config import Pan123Config
                pan123_config = Pan123Config(
                    client_id=config.pan123.client_id,
                    client_secret=config.pan123.client_secret,
                    root_dir_id=pan123_root_dir,
                    access_token=config.pan123.access_token,
                    token_expires_at=config.pan123.token_expires_at
                )
            else:
                pan123_config = config.pan123
        else:
            pan123_config = config.pan123

        return {
            "success": True,
            "pan123": {
                "root_dir_id": pan123_config.root_dir_id
            }
        }
    except Exception as e:
        logger.error(f"获取公开配置失败: {e}")
        return {
            "success": False,
            "pan123": {
                "root_dir_id": 0
            }
        }


@router.get("/config", response_model=ConfigResponse)
async def get_config_api(user_id: str = Depends(require_webui_auth)):
    """获取配置（支持用户配置）"""
    try:
        user_manager = get_user_manager()
        user_config = user_manager.get_user_config(user_id['user_id'])

        # 如果用户有配置，使用用户配置；否则使用全局配置
        config = get_config()

        # 优先使用用户配置
        pan123_config = config.pan123
        if "pan123" in user_config:
            pan123_client_id = user_config["pan123"].get("client_id", config.pan123.client_id)
            pan123_secret = user_config["pan123"].get("client_secret", config.pan123.client_secret)
            pan123_username = user_config["pan123"].get("username", config.pan123.username)
            pan123_password = user_config["pan123"].get("password", config.pan123.password)
            pan123_root_dir = user_config["pan123"].get("root_dir_id", config.pan123.root_dir_id)
            pan123_token = user_config["pan123"].get("access_token", config.pan123.access_token)
            pan123_token_expires = user_config["pan123"].get("token_expires_at", config.pan123.token_expires_at)

            from config import Pan123Config
            pan123_config = Pan123Config(
                client_id=pan123_client_id,
                client_secret=pan123_secret,
                username=pan123_username,
                password=pan123_password,
                root_dir_id=pan123_root_dir,
                access_token=pan123_token,
                token_expires_at=pan123_token_expires
            )

        monitoring_config = config.monitoring
        if "monitoring" in user_config:
            from config import MonitoringConfig
            monitoring_config = MonitoringConfig(**user_config["monitoring"])

        return ConfigResponse(
            server={
                "host": config.server.host,
                "port": config.server.port,
                "cors_origins": config.server.cors_origins
            },
            pan123={
                "client_id": pan123_config.client_id,
                "client_secret": "",  # 不返回secret
                "username": pan123_config.username,
                "password": "",  # 不返回password
                "root_dir_id": pan123_config.root_dir_id
            },
            monitoring={
                "check_interval": monitoring_config.check_interval,
                "max_retries": monitoring_config.max_retries,
                "download_timeout": monitoring_config.download_timeout
            }
        )
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config")
async def update_config(request: ConfigUpdateRequest, user: dict = Depends(require_webui_auth)):
    """更新配置（支持用户配置）"""
    try:
        user_manager = get_user_manager()
        user_id = user['user_id']
        logger.info(f"收到配置更新请求, 用户: {user_id}, 请求数据: {request}")

        # 构建用户配置更新数据
        user_config_data = {}

        # 更新123云盘配置
        if request.pan123:
            pan123_config = {}
            if "client_id" in request.pan123 and request.pan123["client_id"]:
                pan123_config["client_id"] = request.pan123["client_id"]
            if "client_secret" in request.pan123 and request.pan123["client_secret"]:
                pan123_config["client_secret"] = request.pan123["client_secret"]
            if "username" in request.pan123 and request.pan123["username"]:
                pan123_config["username"] = request.pan123["username"]
            if "password" in request.pan123 and request.pan123["password"]:
                pan123_config["password"] = request.pan123["password"]
            if "root_dir_id" in request.pan123 and request.pan123["root_dir_id"] is not None:
                pan123_config["root_dir_id"] = int(request.pan123["root_dir_id"])
            if pan123_config:
                user_config_data["pan123"] = pan123_config

        # 更新监控配置
        if request.monitoring:
            monitoring_config = {}
            if "check_interval" in request.monitoring and request.monitoring["check_interval"] is not None:
                monitoring_config["check_interval"] = int(request.monitoring["check_interval"])
            if "max_retries" in request.monitoring and request.monitoring["max_retries"] is not None:
                monitoring_config["max_retries"] = int(request.monitoring["max_retries"])
            if "download_timeout" in request.monitoring and request.monitoring["download_timeout"] is not None:
                monitoring_config["download_timeout"] = int(request.monitoring["download_timeout"])
            if monitoring_config:
                user_config_data["monitoring"] = monitoring_config

        # 保存用户配置
        if user_config_data:
            logger.info(f"保存配置数据: {user_config_data}")
            user_manager.update_user_config(user_id, user_config_data)
            logger.info(f"用户 {user_id} 配置已更新")
            return {"success": True, "message": "配置已保存"}
        else:
            raise HTTPException(status_code=400, detail="没有提供要更新的配置")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/reset")
async def reset_config(user: dict = Depends(require_webui_auth)):
    """重置用户配置为默认值"""
    try:
        user_manager = get_user_manager()
        user_id = user['user_id']

        # 清除认证服务缓存
        auth_manager = get_auth_manager()
        await auth_manager.get_auth_service(user_id, force_refresh=True)

        # 删除用户配置，然后重新初始化为默认值
        with user_manager.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_configs WHERE user_id = ?", (user_id,))
            conn.commit()

        # 重新初始化用户配置
        user_manager._init_user_config(user_id)

        logger.info(f"用户 {user_id} 配置已重置为默认值")
        return {"success": True, "message": "配置已重置为默认值"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 文件夹API
@router.get("/folders/public")
async def list_folders_public(
    parent_id: int = 0,
    limit: int = 10000,
    request: Request = None
):
    """获取文件夹列表（公开版本，用于folder-picker等不需要登录的场景）"""
    try:
        from api.auth import get_webui_user

        # 尝试获取用户
        user = await get_webui_user(request, Response()) if request else None
        user_id = None

        if user:
            user_id = user.get('user_id')

        if not user_id:
            raise HTTPException(status_code=401, detail="需要登录才能访问文件夹")

        # 获取用户配置
        config = get_user_config(user_id)

        # 检查123云盘配置
        if not config.pan123.client_id and not config.pan123.client_secret and not config.pan123.access_token:
            raise HTTPException(status_code=400, detail="123云盘未配置，请先配置 Client ID/Secret 或使用账号密码登录")

        # 获取认证服务
        auth_manager = get_auth_manager()
        auth_service = await auth_manager.get_auth_service(user_id)

        # 获取文件夹服务（使用 Android 客户端 API，无需开发者权益包）
        folder_service = Pan123AndroidFolderService(auth_service)

        # 获取文件列表（支持大 limit）
        # 如果 limit > 100，使用分批加载获取所有文件
        if limit > 100:
            files = await folder_service.list_all_files(parent_id)
        else:
            files = await folder_service.list_files(parent_id, limit=limit)

        # 只返回文件夹，过滤掉文件和回收站的文件
        folders = [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "parent_file_id": f.parent_file_id,
                "create_at": f.create_at,
                "update_at": f.update_at
            }
            for f in files
            if f.type == 1 and f.trashed == 0  # type=1 表示文件夹，trashed=0 表示不在回收站
        ]

        return {
            "success": True,
            "parent_id": parent_id,
            "folders": folders
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文件夹列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/folders")
async def list_folders(
    parent_id: int = 0,
    limit: int = 10000,  # 默认加载全部
    user_id: str = Depends(require_user_id_from_any_source)
):
    """获取文件夹列表"""
    try:
        # 使用用户配置
        config = get_user_config(user_id)

        # 检查123云盘配置
        if not config.pan123.client_id and not config.pan123.client_secret and not config.pan123.access_token:
            raise HTTPException(status_code=400, detail="123云盘未配置，请先配置 Client ID/Secret 或使用账号密码登录")

        # 获取认证服务
        auth_manager = get_auth_manager()
        auth_service = await auth_manager.get_auth_service(user_id)

        # 获取文件夹服务（使用 Android 客户端 API，无需开发者权益包）
        folder_service = Pan123AndroidFolderService(auth_service)

        # 获取文件列表（支持大 limit）
        # 如果 limit > 100，使用分批加载获取所有文件
        if limit > 100:
            files = await folder_service.list_all_files(parent_id)
        else:
            files = await folder_service.list_files(parent_id, limit=limit)

        # 只返回文件夹，过滤掉文件和回收站的文件
        folders = [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "parent_file_id": f.parent_file_id,
                "create_at": f.create_at,
                "update_at": f.update_at
            }
            for f in files
            if f.type == 1 and f.trashed == 0  # type=1 表示文件夹，trashed=0 表示不在回收站
        ]

        return {
            "success": True,
            "parent_id": parent_id,
            "folders": folders
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文件夹列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/folders")
async def create_folder(
    request: dict,
    user_id: str = Depends(require_user_id_from_any_source)
):
    """创建文件夹"""
    try:
        name = request.get("name", "")
        parent_id = request.get("parent_id", 0)

        if not name or not name.strip():
            raise HTTPException(status_code=400, detail="文件夹名称不能为空")

        # 使用用户配置
        config = get_user_config(user_id)

        # 检查123云盘配置
        if not config.pan123.client_id and not config.pan123.client_secret and not config.pan123.access_token:
            raise HTTPException(status_code=400, detail="123云盘未配置，请先配置 Client ID/Secret 或使用账号密码登录")

        # 获取认证服务
        auth_manager = get_auth_manager()
        auth_service = await auth_manager.get_auth_service(user_id)

        # 获取文件夹服务（使用 Android 客户端 API，无需开发者权益包）
        folder_service = Pan123AndroidFolderService(auth_service)

        # 创建文件夹
        dir_id = await folder_service.create_folder(name.strip(), parent_id)

        return {
            "success": True,
            "dir_id": dir_id,
            "message": "文件夹创建成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建文件夹失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/folder/trash")
async def trash_folder(
    request: dict,
    user_id: str = Depends(require_user_id_from_any_source)
):
    """将文件/文件夹移至回收站"""
    try:
        file_ids = request.get("file_ids", [])

        if not file_ids or not isinstance(file_ids, list):
            raise HTTPException(status_code=400, detail="file_ids 参数无效")

        if len(file_ids) == 0:
            raise HTTPException(status_code=400, detail="请选择要删除的文件")

        if len(file_ids) > 100:
            raise HTTPException(status_code=400, detail="一次性最多删除 100 个文件")

        # 使用用户配置
        config = get_user_config(user_id)

        # 检查123云盘配置
        if not config.pan123.client_id and not config.pan123.client_secret and not config.pan123.access_token:
            raise HTTPException(status_code=400, detail="123云盘未配置，请先配置 Client ID/Secret 或使用账号密码登录")

        # 获取认证服务
        auth_manager = get_auth_manager()
        auth_service = await auth_manager.get_auth_service(user_id)

        # 获取文件夹服务（使用 Android 客户端 API，无需开发者权益包）
        folder_service = Pan123AndroidFolderService(auth_service)

        # 调用删除API（移至回收站）
        success = await folder_service.trash_files(file_ids)

        if success:
            return {
                "success": True,
                "message": "文件已移至回收站"
            }
        else:
            raise HTTPException(status_code=500, detail="删除文件失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 日志API
class LogEntry(BaseModel):
    """日志条目模型"""
    time: str
    level: str
    message: str


@router.get("/logs")
async def get_logs(level: Optional[str] = None, limit: int = 100, user_id: Optional[str] = Depends(get_webui_user_id)):
    """获取用户专属日志"""
    try:
        from pathlib import Path

        # 如果没有用户ID,使用默认日志
        if user_id is None:
            log_file = Path(__file__).parent.parent / "logs" / "server.log"
        else:
            # 使用用户的专属日志路径
            log_file = Path(__file__).parent.parent / "logs" / f"user_{user_id}.log"

        if not log_file.exists():
            # 如果日志文件不存在,返回空列表
            logger.warning(f"日志文件不存在: {log_file}")
            return {"logs": []}

        logs = []
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            # 取最后limit行
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue

                # 解析日志格式: {time} | {level} | {message}
                # 使用正则表达式来解析，更加健壮
                import re as regex_module
                match = regex_module.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\|\s*([A-Z]+)\s+\|\s*(.+)$', line)
                if match:
                    log_time = match.group(1)
                    log_level = match.group(2).lower()
                    log_message = match.group(3)

                    # 过滤级别
                    if level and level != "all" and log_level != level:
                        continue

                    logs.append({
                        "time": log_time,
                        "level": log_level,
                        "message": log_message
                    })
                else:
                    # 如果解析失败，记录调试信息
                    pass

        # 反转顺序，最新的在前
        logs.reverse()
        return {"logs": logs}

    except Exception as e:
        logger.error(f"获取用户日志失败: {e}")
        # 如果日志文件不存在，返回空列表而不是抛出异常
        return {"logs": []}


@router.delete("/logs")
async def clear_logs(user: dict = Depends(require_webui_auth)):
    """清空用户专属日志"""
    try:
        from api.user_logger import delete_user_log
        user_id = user['user_id']

        # 删除用户日志文件
        delete_user_log(user_id)

        return {"success": True, "message": "日志已清空"}
    except Exception as e:
        logger.error(f"清空日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 服务器控制API
@router.post("/server/stop")
async def stop_server_api():
    """停止监控服务"""
    try:
        from api.server import stop_server as stop_server_func
        await stop_server_func()
        return {"success": True, "message": "监控服务已停止"}
    except Exception as e:
        logger.error(f"停止监控服务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/logs/test")
async def test_user_log(user: dict = Depends(require_webui_auth)):
    """测试用户日志功能"""
    try:
        from api.user_logger import add_user_log_handler
        user_id = user['user_id']

        # 添加日志handler
        add_user_log_handler(user_id)

        # 写入测试日志
        test_logger = logger.bind(user_id=user_id)
        test_logger.info("这是一条测试日志")
        test_logger.warning("这是一条测试警告日志")
        test_logger.error("这是一条测试错误日志")

        return {"success": True, "message": "测试日志已写入"}
    except Exception as e:
        logger.error(f"测试日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/server/start")
async def start_server_api():
    """启动监控服务"""
    try:
        from api.server import start_server as start_server_func
        await start_server_func()
        return {"success": True, "message": "监控服务已启动"}
    except Exception as e:
        logger.error(f"启动监控服务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/server/status")
async def get_server_status():
    """获取服务器状态"""
    try:
        from api.server import get_monitor_service
        monitor_service = get_monitor_service()
        is_running = monitor_service is not None and monitor_service._running
        return {
            "success": True,
            "server_running": True,  # HTTP服务器总是运行的
            "monitor_running": is_running
        }
    except Exception as e:
        logger.error(f"获取服务器状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== Token API ==========

@router.get("/auth/pan123/token", response_model=Pan123TokenResponse)
async def get_pan123_token(user_id: str = Depends(require_user_id_from_any_source)):
    """获取123云盘访问令牌（使用Client ID/Secret直接获取新Token）"""
    try:
        # 获取用户配置
        from services.user_manager import get_user_manager
        from services.pan123_service import Pan123AuthService
        user_manager = get_user_manager()
        user_config = user_manager.get_user_config(user_id)

        # 获取全局配置作为默认值
        config = get_config()

        # 优先使用用户配置
        pan123_config = user_config.get("pan123", {})
        client_id = pan123_config.get("client_id", config.pan123.client_id)
        client_secret = pan123_config.get("client_secret", config.pan123.client_secret)
        username = pan123_config.get("username", config.pan123.username)
        password = pan123_config.get("password", config.pan123.password)
        root_dir_id = pan123_config.get("root_dir_id", config.pan123.root_dir_id)

        # 检查是否有认证信息
        if not ((client_id and client_secret) or (username and password)):
            return Pan123TokenResponse(
                success=False,
                access_token=None,
                expired_at=None,
                root_dir_id=root_dir_id,
                message="未配置认证信息，请在设置页面填写Client ID/Secret或用户名密码"
            )

        # 直接创建新的认证服务实例并获取token（不使用缓存）
        auth_service = Pan123AuthService(
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password
        )

        # 强制获取新token（不使用缓存的旧token）
        token = await auth_service.get_access_token()
        expired_at = auth_service._token_expires_at

        if not token or not expired_at:
            return Pan123TokenResponse(
                success=False,
                access_token=None,
                expired_at=None,
                root_dir_id=root_dir_id,
                message="获取Token失败，请检查Client ID和Client Secret是否正确"
            )

        # 更新token到用户配置
        user_manager.update_user_config(user_id, {
            "pan123": {
                "access_token": token,
                "token_expires_at": expired_at.isoformat()
            }
        })

        logger.info(f"获取123云盘Token成功: 用户={user_id}")
        return Pan123TokenResponse(
            success=True,
            access_token=token,
            expired_at=expired_at.isoformat(),
            root_dir_id=root_dir_id,
            message="获取Token成功"
        )

    except Exception as e:
        import traceback
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else repr(e)
        error_detail = f"{error_type}: {error_msg}"
        logger.error(f"获取123云盘Token失败: {error_detail}")
        logger.debug(f"异常堆栈:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_detail)


# ========== 视频信息API ==========

@router.post("/video/save", response_model=dict)
async def save_video_info(request: VideoCreateRequest, user_id: str = Depends(require_user_id_from_any_source)):
    """保存或更新视频信息（并下载封面到本地）"""
    try:
        from services.database import get_database
        db = get_database()
        from pathlib import Path
        import aiohttp
        import asyncio

        from datetime import datetime
        now = datetime.now().isoformat()

        # 下载封面到本地
        local_cover_url = None
        if request.cover_url:
            try:
                # 创建封面目录（使用分片存储）
                project_dir = Path(__file__).parent.parent
                covers_dir = project_dir / "data" / "covers"
                covers_dir.mkdir(parents=True, exist_ok=True)

                # 生成封面文件名和路径（使用 video_id 前两位作为子目录）
                cover_filename = f"{request.video_id}.jpg"
                subdir = str(request.video_id)[:2] if len(str(request.video_id)) >= 2 else "00"
                cover_subdir = covers_dir / subdir
                cover_subdir.mkdir(parents=True, exist_ok=True)
                cover_path = cover_subdir / cover_filename

                # 如果文件已存在，直接使用本地路径
                if cover_path.exists():
                    local_cover_url = f"/covers/{subdir}/{cover_filename}"
                    logger.info(f"封面已存在: {cover_path}")
                else:
                    # 下载封面图片（带重试机制）
                    downloaded_path = await download_cover_with_retry(request.cover_url, cover_path)
                    if downloaded_path:
                        local_cover_url = f"/covers/{subdir}/{cover_filename}"
            except Exception as e:
                logger.warning(f"下载封面失败: {e}")
                # 下载失败时，使用原始URL

        # 处理发布时间，如果有release_time则转换为ISO格式
        created_at = now
        if request.release_time:
            try:
                # release_time格式为YYYYMMDD，转换为ISO格式
                release_date = datetime.strptime(request.release_time, "%Y%m%d")
                created_at = release_date.isoformat()
                logger.info(f"使用发布时间: {request.release_time} -> {created_at}")
            except ValueError as e:
                logger.warning(f"发布时间格式错误: {request.release_time}, 使用当前时间")

        video_data = {
            "video_id": request.video_id,
            "title": request.title,
            "series_name": request.series_name,
            "cover_url": local_cover_url if local_cover_url else request.cover_url,
            "duration": request.duration,
            "local_url": request.local_url,
            "created_at": created_at,
            "updated_at": now,
            "user_id": user_id,
            "rename_name": request.rename_name
        }

        success = db.create_or_update_video(video_data)

        if success:
            return {"success": True, "message": "视频信息保存成功"}
        else:
            raise HTTPException(status_code=500, detail="保存视频信息失败")
    except Exception as e:
        logger.error(f"保存视频信息时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"保存视频信息失败: {str(e)}")


# ========== 封面更新模型 ==========
class CoverUpdateRequest(BaseModel):
    """封面更新请求模型"""
    video_id: int = Field(..., description="视频ID")
    cover_url: Optional[str] = Field(None, description="封面URL")
    cover_data: Optional[str] = Field(None, description="封面图片base64数据（DataURL）")


@router.post("/video/update-cover", response_model=dict)
async def update_video_cover(request: CoverUpdateRequest, user_id: str = Depends(require_user_id_from_any_source)):
    """更新视频封面"""
    try:
        from services.database import get_database
        db = get_database()
        from pathlib import Path
        import aiohttp
        import asyncio

        from datetime import datetime
        now = datetime.now().isoformat()

        # 检查视频是否存在
        existing_video = db.get_video(request.video_id)

        # 创建封面目录和路径（提前准备）
        project_dir = Path(__file__).parent.parent
        covers_dir = project_dir / "data" / "covers"
        covers_dir.mkdir(parents=True, exist_ok=True)
        cover_filename = f"{request.video_id}.jpg"
        subdir = str(request.video_id)[:2] if len(str(request.video_id)) >= 2 else "00"
        cover_subdir = covers_dir / subdir
        cover_subdir.mkdir(parents=True, exist_ok=True)
        cover_path = cover_subdir / cover_filename

        # 优先处理 cover_data（base64 DataURL）
        if request.cover_data:
            import base64, re
            match = re.match(r"data:image/\w+;base64,(.+)", request.cover_data)
            if match:
                img_data = base64.b64decode(match.group(1))
                with open(cover_path, "wb") as f:
                    f.write(img_data)
                logger.info(f"已保存base64封面: {cover_path}")
                return {
                    "success": True,
                    "message": "封面已通过base64上传并保存",
                    "stats": {"checked": 1, "already_exists": 0, "downloaded": 1, "failed": 0}
                }
            else:
                logger.warning("cover_data 格式不正确，未能保存图片")
                return {
                    "success": False,
                    "message": "cover_data 格式不正确，未能保存图片",
                    "stats": {"checked": 1, "already_exists": 0, "downloaded": 0, "failed": 1}
                }

        if existing_video:
            # 视频存在的情况
            # 检查是否已有封面
            if db.has_video_cover(request.video_id, user_id):
                logger.info(f"视频 {request.video_id} 已有封面，跳过更新")
                return {
                    "success": True,
                    "message": "视频已有封面，无需更新",
                    "stats": {
                        "checked": 1,
                        "already_exists": 1,
                        "downloaded": 0,
                        "failed": 0
                    }
                }

            # 下载封面到本地
            local_cover_url = None
            if request.cover_url:
                try:
                    # 如果文件已存在，直接使用本地路径
                    if cover_path.exists():
                        local_cover_url = f"/covers/{subdir}/{cover_filename}"
                        logger.info(f"封面已存在: {cover_path}")
                    else:
                        # 下载封面图片（带重试机制）
                        downloaded_path = await download_cover_with_retry(request.cover_url, cover_path)
                        if downloaded_path:
                            local_cover_url = f"/covers/{subdir}/{cover_filename}"
                except Exception as e:
                    logger.warning(f"下载封面失败: {e}")
                    # 下载失败时，使用原始URL

            # 更新视频封面
            update_data = {
                "cover_url": local_cover_url if local_cover_url else request.cover_url,
                "updated_at": now
            }

            success = db.update_video_cover(request.video_id, update_data, user_id)

            if success:
                message = "封面更新成功"
                if local_cover_url:
                    message += " (已下载到本地)"
                return {
                    "success": True,
                    "message": message,
                    "stats": {
                        "checked": 1,
                        "already_exists": 0,
                        "downloaded": 1,
                        "failed": 0
                    }
                }
            else:
                raise HTTPException(status_code=500, detail="封面更新失败")
        else:
            # 视频不存在的情况：仍然下载封面，为将来推送视频做准备
            logger.info(f"视频 {request.video_id} 不存在，但仍尝试下载封面")

            # 检查封面文件是否已存在
            if cover_path.exists():
                logger.info(f"封面文件已存在: {cover_path}")
                return {
                    "success": True,
                    "message": "封面文件已存在，无需下载",
                    "stats": {
                        "checked": 1,
                        "already_exists": 1,
                        "downloaded": 0,
                        "failed": 0
                    }
                }

            # 下载封面到本地
            local_cover_url = None
            if request.cover_url:
                try:
                    # 下载封面图片（带重试机制）
                    downloaded_path = await download_cover_with_retry(request.cover_url, cover_path)
                    if downloaded_path:
                        local_cover_url = f"/covers/{subdir}/{cover_filename}"
                        logger.info(f"封面下载成功: {cover_path}")
                        return {
                            "success": True,
                            "message": "封面下载成功（视频不存在，将来推送视频时可直接使用）",
                            "stats": {
                                "checked": 1,
                                "already_exists": 0,
                                "downloaded": 1,
                                "failed": 0
                            }
                        }
                    else:
                        logger.warning(f"封面下载失败: {request.cover_url}")
                        return {
                            "success": False,
                            "message": "封面下载失败",
                            "stats": {
                                "checked": 1,
                                "already_exists": 0,
                                "downloaded": 0,
                                "failed": 1
                            }
                        }
                except Exception as e:
                    logger.warning(f"下载封面失败: {e}")
                    return {
                        "success": False,
                        "message": f"封面下载失败: {str(e)}",
                        "stats": {
                            "checked": 1,
                            "already_exists": 0,
                            "downloaded": 0,
                            "failed": 1
                        }
                    }
            else:
                return {
                    "success": False,
                    "message": "未提供封面URL",
                    "stats": {
                        "checked": 1,
                        "already_exists": 0,
                        "downloaded": 0,
                        "failed": 1
                    }
                }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else repr(e)
        error_detail = f"{error_type}: {error_msg}"

        logger.error(f"更新视频封面失败: {error_detail}")
        logger.debug(f"异常堆栈:\n{traceback.format_exc()}")

        raise HTTPException(status_code=500, detail=error_detail)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存视频信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/videos", response_model=VideoListResponse)
async def list_videos(
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    year: Optional[str] = None,
    month: Optional[str] = None,
    time_range: Optional[str] = None,
    user_id: str = Depends(require_webui_auth)
):
    """获取视频列表（显示所有用户的视频，支持搜索、分页、排序、时间筛选）"""
    try:
        from services.database import get_database
        db = get_database()
        from pathlib import Path

        # 构建time_filter参数
        time_filter = None
        if time_range:
            time_filter = time_range
        elif year:
            time_filter = f"{year}-{month}" if month else f"{year}"
        elif month:
            # 只有月份，没有年份，表示筛选所有年份的该月份
            time_filter = f"-{month}"

        # 不传user_id，显示所有用户的视频（公共视频库）
        result = db.get_all_videos(
            user_id=None,  # 不限制用户，显示所有视频
            search=search,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            time_filter=time_filter
        )

        # 检查本地covers文件夹，更新封面URL
        project_dir = Path(__file__).parent.parent
        covers_dir = project_dir / "data" / "covers"

        for video in result["videos"]:
            if video.get("video_id"):
                # 生成封面文件路径（使用 video_id 前两位作为子目录）
                subdir = str(video["video_id"])[:2] if len(str(video["video_id"])) >= 2 else "00"
                cover_path = covers_dir / subdir / f"{video['video_id']}.jpg"

                # 如果本地存在封面，使用本地URL
                if cover_path.exists():
                    video["cover_url"] = f"/covers/{subdir}/{video['video_id']}.jpg"

        return VideoListResponse(
            videos=result["videos"],
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"]
        )

    except Exception as e:
        logger.error(f"获取视频列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/video/{video_id}", response_model=VideoInfo)
async def get_video_info(video_id: str, user_id: str = Depends(require_webui_auth)):
    """获取视频信息"""
    try:
        from services.database import get_database
        db = get_database()

        video = db.get_video(video_id)

        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")

        return VideoInfo(**video)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取视频信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/video/{video_id}")
async def delete_video(video_id: str, user_id: str = Depends(require_webui_auth)):
    """删除视频"""
    try:
        from services.database import get_database
        db = get_database()

        success = db.delete_video(video_id)

        if success:
            return {"success": True, "message": "删除成功"}
        else:
            raise HTTPException(status_code=404, detail="视频不存在")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除视频失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/video/{video_id}/push-cover")
async def push_video_cover(video_id: str, user: dict = Depends(require_webui_auth)):
    """推送视频封面到云端"""
    try:
        user_id = user["user_id"]
        from services.database import get_database
        from services.pan123_service import Pan123FolderService
        import hashlib
        import aiofiles
        import os
        from pathlib import Path

        db = get_database()

        # 获取视频信息
        video = db.get_video(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")

        # 检查是否有封面文件（优先检查文件存在性，而不是数据库中的URL）
        # 封面文件存储在子目录中，子目录是video_id的前两位数字
        subdir = str(video_id)[:2] if len(str(video_id)) >= 2 else "00"
        cover_path = Path(__file__).parent.parent / "data" / "covers" / subdir / f"{video_id}.jpg"
        if not cover_path.exists():
            raise HTTPException(status_code=404, detail="封面文件不存在")

        # 获取用户配置
        config = get_user_config(user_id)

        # 检查123云盘配置
        if not config.pan123.client_id and not config.pan123.client_secret and not config.pan123.access_token:
            raise HTTPException(status_code=400, detail="123云盘未配置，请先配置 Client ID/Secret 或使用账号密码登录")

        # 获取认证服务
        auth_manager = get_auth_manager()
        auth_service = await auth_manager.get_auth_service(user_id)

        # 读取封面文件
        async with aiofiles.open(cover_path, 'rb') as f:
            cover_data = await f.read()

        # 计算文件MD5
        file_md5 = hashlib.md5(cover_data).hexdigest()
        file_size = len(cover_data)

        # 生成文件名：原文件名-poster.jpg
        original_filename = video.get('rename_name', video.get('title', video_id))
        # 移除扩展名
        if '.' in original_filename:
            base_name = original_filename.rsplit('.', 1)[0]
        else:
            base_name = original_filename

        poster_filename = f"{base_name}-poster.jpg"

        # 清理文件名（移除非法字符）
        poster_filename = poster_filename.replace('<', '_').replace('>', '_').replace(':', '_').replace('"', '_').replace('|', '_').replace('?', '_').replace('*', '_')

        # 确保文件名不为空且不全为空格
        if not poster_filename.strip():
            poster_filename = f"{video_id}-poster.jpg"

        # 限制文件名长度
        if len(poster_filename) > 250:
            poster_filename = poster_filename[:250] + ".jpg"

        # 查找视频文件所在的目录（使用 Android 客户端 API）
        folder_service = Pan123AndroidFolderService(auth_service)
        root_dir_id = config.pan123.root_dir_id

        target_folder_id = None

        # 首先尝试从数据库的created_at确定路径
        video_title = video.get('title', '')
        created_at = video.get('created_at', '')

        if created_at:
            try:
                # 解析created_at时间
                if isinstance(created_at, str):
                    # 支持多种时间格式
                    if 'T' in created_at:
                        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    else:
                        dt = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
                else:
                    dt = datetime.fromtimestamp(created_at)

                year = str(dt.year)
                month = str(dt.month).zfill(2)

                # 查找年份文件夹
                year_folder_id = await folder_service.find_folder(year, root_dir_id)
                if year_folder_id:
                    # 查找月份文件夹
                    month_folder_id = await folder_service.find_folder(month, year_folder_id)
                    if month_folder_id:
                        target_folder_id = month_folder_id
                        logger.info(f"根据创建时间确定目录: {year}/{month}, ID: {month_folder_id}")

            except Exception as e:
                logger.warning(f"解析创建时间失败: {e}")

        # 如果还是找不到目标目录，使用根目录
        if not target_folder_id:
            target_folder_id = root_dir_id
            logger.warning(f"无法确定视频 {video_id} 的目录路径，上传到根目录")

        # 在目标目录中上传封面
        upload_url = "https://openapi-upload.123242.com"

        import aiohttp

        data = aiohttp.FormData()
        data.add_field('parentFileID', str(target_folder_id))
        data.add_field('filename', poster_filename)
        data.add_field('etag', file_md5)
        data.add_field('size', str(file_size))
        data.add_field('file', cover_data, filename=poster_filename, content_type='image/jpeg')

        headers = {
            'Authorization': auth_service.get_auth_header(),
            'Platform': 'open_platform'
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(upload_url + '/upload/v2/file/single/create', data=data, headers=headers) as response:
                result = await response.json()

                if result.get('code') == 0:
                    logger.info(f"封面上传成功: {poster_filename}, 文件ID: {result['data']['fileID']}")
                    return {
                        "success": True,
                        "message": f"封面上传成功: {poster_filename}",
                        "file_id": result['data']['fileID']
                    }
                else:
                    error_msg = result.get('message', '未知错误')
                    logger.error(f"封面上传失败: {error_msg}")
                    raise HTTPException(status_code=500, detail=f"上传失败: {error_msg}")

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"推送封面失败: {e}")
        logger.debug(f"异常堆栈:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/videos/export")
async def export_videos(user: dict = Depends(require_webui_auth)):
    """导出所有视频数据及封面（仅管理员）"""
    try:
        # 验证是否为admin用户
        from services.user_manager import get_user_manager
        user_manager = get_user_manager()
        user_id = user['user_id']

        # 获取当前用户的username
        with user_manager.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="用户不存在")

            if row["username"] != "admin":
                raise HTTPException(status_code=403, detail="只有管理员可以导出视频数据")

        # 获取所有视频
        from services.database import get_database
        from pathlib import Path
        from datetime import datetime
        import zipfile
        import io

        db = get_database()
        result = db.get_all_videos(
            user_id=None,  # 不限制用户，导出所有视频
            page=1,
            page_size=100000  # 导出所有视频
        )

        videos = result["videos"]

        # 创建内存中的ZIP文件
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 添加元数据文件
            metadata = {
                "export_time": datetime.now().isoformat(),
                "total_count": len(videos),
                "version": "2.0",
                "videos": videos
            }
            zipf.writestr("metadata.json", json.dumps(metadata, indent=2, ensure_ascii=False))

            # 添加封面图片
            covers_path = Path(__file__).parent.parent / "data" / "covers"
            covers_added = 0

            for video in videos:
                video_id = video.get("video_id")
                if not video_id:
                    continue

                # 查找封面文件
                potential_cover_dirs = [
                    covers_path / video_id[:2] / f"{video_id}.jpg",
                    covers_path / video_id[:2] / f"{video_id}.png",
                    covers_path / video_id[:2] / f"{video_id}.webp"
                ]

                for cover_path in potential_cover_dirs:
                    if cover_path.exists():
                        # 在ZIP中保持相对路径: covers/{video_id}.{ext}
                        relative_path = f"covers/{video_id}{cover_path.suffix}"
                        zipf.write(cover_path, relative_path)
                        covers_added += 1
                        break

            logger.info(f"导出完成: {len(videos)} 个视频, {covers_added} 个封面")

        # 设置ZIP缓冲区的位置到开头
        zip_buffer.seek(0)

        # 返回ZIP文件
        from fastapi.responses import StreamingResponse
        from datetime import datetime

        filename = f"videos_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

        def generate():
            yield zip_buffer.getvalue()

        return StreamingResponse(
            generate(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出视频失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class VideoImportRequest(BaseModel):
    """视频导入请求模型"""
    videos: list


@router.post("/videos/import")
async def import_videos(request: VideoImportRequest, user: dict = Depends(require_webui_auth)):
    """导入视频数据及封面（仅管理员）"""
    try:
        # 验证是否为admin用户
        from services.user_manager import get_user_manager
        user_manager = get_user_manager()
        user_id = user['user_id']

        # 获取当前用户的username
        with user_manager.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="用户不存在")

            if row["username"] != "admin":
                raise HTTPException(status_code=403, detail="只有管理员可以导入视频数据")

        # 导入视频（跳过已存在的）
        from services.database import get_database
        from pathlib import Path
        from datetime import datetime
        import base64

        db = get_database()

        imported_count = 0
        skipped_count = 0
        failed_count = 0
        covers_imported = 0

        # 获取已存在的video_id列表
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT video_id FROM videos")
            existing_video_ids = {row[0] for row in cursor.fetchall()}

        for video_data in request.videos:
            try:
                video_id = video_data.get("video_id")
                title = video_data.get("title")

                # 验证必需字段
                if not video_id or not title:
                    failed_count += 1
                    continue

                # 检查是否已存在
                if video_id in existing_video_ids:
                    skipped_count += 1
                    logger.info(f"跳过已存在的视频: {video_id} - {title}")
                    continue

                # 准备视频数据
                # 旧数据没有 incomplete 字段，默认设置为 1（完善视频）
                video = {
                    "video_id": video_id,
                    "title": title,
                    "series_name": video_data.get("series_name"),
                    "cover_url": video_data.get("cover_url"),
                    "duration": video_data.get("duration"),
                    "local_url": video_data.get("local_url"),
                    "created_at": video_data.get("created_at", datetime.now().isoformat()),
                    "updated_at": datetime.now().isoformat(),
                    "user_id": video_data.get("user_id"),
                    "incomplete": video_data.get("incomplete", 1)  # 旧数据默认为完善视频
                }

                # 保存视频
                success = db.create_or_update_video(video)
                if success:
                    imported_count += 1
                    # 添加到已存在列表，防止重复导入
                    existing_video_ids.add(video_id)
                else:
                    failed_count += 1

                # 处理封面图片（如果有base64数据）
                cover_data = video_data.get("cover_data")
                if cover_data and video_id:
                    try:
                        # 解码base64
                        image_data = base64.b64decode(cover_data)

                        # 保存封面
                        covers_path = Path(__file__).parent.parent / "data" / "covers"
                        cover_dir = covers_path / video_id[:2]
                        cover_dir.mkdir(parents=True, exist_ok=True)

                        # 根据数据判断格式
                        if image_data.startswith(b'\x89PNG'):
                            ext = ".png"
                        elif image_data.startswith(b'\xff\xd8'):
                            ext = ".jpg"
                        elif image_data.startswith(b'RIFF') and b'WEBP' in image_data[:12]:
                            ext = ".webp"
                        else:
                            ext = ".jpg"  # 默认

                        cover_path = cover_dir / f"{video_id}{ext}"
                        with open(cover_path, 'wb') as f:
                            f.write(image_data)
                        covers_imported += 1
                        logger.info(f"封面已保存: {cover_path}")
                    except Exception as e:
                        logger.warning(f"保存封面失败: {video_id}, 错误: {e}")

            except Exception as e:
                logger.warning(f"导入视频失败: {video_data.get('video_id', 'unknown')}, 错误: {e}")
                failed_count += 1

        logger.info(f"视频导入完成: 导入 {imported_count}, 跳过 {skipped_count}, 失败 {failed_count}, 封面 {covers_imported}")

        return {
            "success": True,
            "imported": imported_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "covers_imported": covers_imported,
            "message": f"导入完成：导入 {imported_count} 个，跳过 {skipped_count} 个，失败 {failed_count} 个，封面 {covers_imported} 个"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入视频失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
