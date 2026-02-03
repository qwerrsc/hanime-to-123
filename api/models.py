"""
API 数据模型定义
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"           # 等待处理
    DOWNLOADING = "downloading"   # 下载中
    RENAMING = "renaming"         # 重命名中
    COVER_UPLOADING = "cover_uploading"     # 封面上传中
    COMPLETED = "completed"       # 已完成
    COVER_UPLOAD_FAILED = "cover_upload_failed"  # 封面上传失败
    FAILED = "failed"             # 失败


class VideoSubmitRequest(BaseModel):
    """视频提交请求模型"""
    video_id: str = Field(..., description="视频ID")
    title: str = Field(..., description="视频标题")
    download_url: Optional[str] = Field(None, description="视频下载链接（可选，系列下载时可能为空）")
    folder_name: str = Field(..., description="年份文件夹（如2025）")
    month_folder: Optional[str] = Field(None, description="月份文件夹（如10）")
    parent_dir_id: Optional[int] = Field(None, description="父目录ID，默认使用配置的根目录")
    rename_name: Optional[str] = Field(None, description="重命名文件名（如 [20250627]标题）")


class VideoSubmitResponse(BaseModel):
    """视频提交响应模型"""
    success: bool = Field(..., description="是否成功")
    task_id: str = Field(..., description="任务ID")
    folder_id: int = Field(..., description="创建的文件夹ID")
    download_task_id: Optional[int] = Field(None, description="123云盘离线下载任务ID")
    message: Optional[str] = Field(None, description="提示信息")


class TaskInfo(BaseModel):
    """任务信息模型"""
    task_id: str = Field(..., description="任务ID")
    video_id: str = Field(..., description="视频ID")
    title: str = Field(..., description="视频标题")
    folder_id: int = Field(..., description="创建的文件夹ID")
    folder_name: str = Field(..., description="文件夹名称")
    download_task_id: Optional[int] = Field(None, description="离线下载任务ID")
    status: TaskStatus = Field(..., description="任务状态")
    progress: float = Field(0.0, description="下载进度 0-100")
    file_id: Optional[int] = Field(None, description="下载后的文件ID")
    desired_name: Optional[str] = Field(None, description="目标文件名")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    error_message: Optional[str] = Field(None, description="错误信息")


class TaskStatusResponse(BaseModel):
    """任务状态响应模型"""
    task_id: str = Field(..., description="任务ID")
    status: TaskStatus = Field(..., description="任务状态")
    progress: float = Field(0.0, description="下载进度 0-100")
    message: Optional[str] = Field(None, description="状态描述")


class TaskListResponse(BaseModel):
    """任务列表响应模型"""
    tasks: List[TaskInfo] = Field(default_factory=list, description="任务列表")
    total: int = Field(0, description="任务总数")


class TaskStatisticsResponse(BaseModel):
    """任务统计响应模型"""
    total: int = Field(0, description="总任务数")
    pending: int = Field(0, description="等待中")
    downloading: int = Field(0, description="下载中")
    renaming: int = Field(0, description="重命名中")
    completed: int = Field(0, description="已完成")
    failed: int = Field(0, description="失败")


class HealthResponse(BaseModel):
    """健康检查响应模型"""
    status: str = Field("ok", description="服务状态")
    version: str = Field("1.0.0", description="版本号")


class ErrorResponse(BaseModel):
    """错误响应模型"""
    success: bool = Field(False, description="是否成功")
    message: str = Field(..., description="错误信息")
    code: Optional[int] = Field(None, description="错误码")


class FolderFileInfo(BaseModel):
    """文件夹中的文件信息"""
    file_id: int = Field(..., description="文件ID")
    filename: str = Field(..., description="文件名")
    size: int = Field(..., description="文件大小")
    category: int = Field(..., description="文件分类：0-未知 1-音频 2-视频 3-图片")


class FolderCheckRequest(BaseModel):
    """文件夹检查请求模型"""
    folder_name: str = Field(..., description="文件夹名称")
    parent_dir_id: Optional[int] = Field(None, description="父目录ID，默认使用配置的根目录")
    video_title: Optional[str] = Field(None, description="视频标题（用于检查是否已存在）")
    series_titles: Optional[List[str]] = Field(None, description="系列视频标题列表（用于检查缺少的集数）")


class FolderCheckResponse(BaseModel):
    """文件夹检查响应模型"""
    folder_exists: bool = Field(..., description="文件夹是否存在")
    folder_id: Optional[int] = Field(None, description="文件夹ID（如果存在）")
    files: List[FolderFileInfo] = Field(default_factory=list, description="文件夹中的文件列表")
    video_exists: bool = Field(False, description="视频是否已存在")
    missing_episodes: List[str] = Field(default_factory=list, description="缺少的集数标题列表")
    message: Optional[str] = Field(None, description="提示信息")
    suggest_manual_select: bool = Field(False, description="是否建议手动选择文件夹")
    root_dir_id: int = Field(0, description="用户配置的根目录ID")


# ========== 用户认证模型 ==========

class UserRegisterRequest(BaseModel):
    """用户注册请求"""
    username: str = Field(..., description="用户名", min_length=3, max_length=50)
    password: str = Field(..., description="密码", min_length=6, max_length=100)


class UserLoginRequest(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class UserLoginResponse(BaseModel):
    """用户登录响应"""
    success: bool = Field(..., description="是否成功")
    user_id: str = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    api_key: str = Field(..., description="API密钥")
    message: str = Field(..., description="提示信息")


class UserRegenerateApiKeyRequest(BaseModel):
    """重新生成API密钥请求"""
    user_id: str = Field(..., description="用户ID")
    password: str = Field(..., description="密码（用于验证）")


class UserRegenerateApiKeyResponse(BaseModel):
    """重新生成API密钥响应"""
    success: bool = Field(..., description="是否成功")
    api_key: str = Field(..., description="新的API密钥")
    message: str = Field(..., description="提示信息")


class UserInfo(BaseModel):
    """用户信息"""
    user_id: str = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    created_at: str = Field(..., description="创建时间")
    last_login: Optional[str] = Field(None, description="最后登录时间")
    is_active: bool = Field(..., description="是否激活")


class UsersListResponse(BaseModel):
    """用户列表响应"""
    users: List[UserInfo] = Field(default_factory=list, description="用户列表")
    total: int = Field(0, description="用户总数")


# ========== 123云盘Token模型 ==========

class Pan123TokenResponse(BaseModel):
    """123云盘Token响应"""
    success: bool = Field(..., description="是否成功")
    access_token: Optional[str] = Field(None, description="访问令牌")
    expired_at: Optional[str] = Field(None, description="过期时间")
    root_dir_id: Optional[int] = Field(None, description="根目录ID")
    message: Optional[str] = Field(None, description="提示信息")


# ========== 视频信息模型 ==========

class VideoInfo(BaseModel):
    """视频信息"""
    video_id: str = Field(..., description="视频ID")
    title: str = Field(..., description="视频标题")
    series_name: Optional[str] = Field(None, description="系列名称（原日文标题）")
    cover_url: Optional[str] = Field(None, description="封面URL")
    duration: Optional[str] = Field(None, description="视频时长")
    local_url: Optional[str] = Field(None, description="本地链接")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")
    rename_name: Optional[str] = Field(None, description="重命名文件名（如 [20250627]标题）")


class VideoCreateRequest(BaseModel):
    """创建/更新视频信息请求"""
    video_id: str = Field(..., description="视频ID")
    title: str = Field(..., description="视频标题")
    series_name: Optional[str] = Field(None, description="系列名称（原日文标题）")
    cover_url: Optional[str] = Field(None, description="封面URL")
    duration: Optional[str] = Field(None, description="视频时长")
    local_url: Optional[str] = Field(None, description="本地链接")
    release_time: Optional[str] = Field(None, description="发布时间（YYYYMMDD格式）")
    rename_name: Optional[str] = Field(None, description="重命名文件名（如 [20250627]h3标题）")


class VideoListResponse(BaseModel):
    """视频列表响应"""
    videos: List[VideoInfo] = Field(default_factory=list, description="视频列表")
    total: int = Field(0, description="总数")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(20, description="每页数量")
    total_pages: int = Field(1, description="总页数")
