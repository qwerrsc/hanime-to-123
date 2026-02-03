"""
123云盘 API 服务
"""
import httpx
import json
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime
from loguru import logger
import asyncio
import time


@dataclass
class FileInfo:
    """文件信息"""
    file_id: int
    filename: str
    parent_file_id: int
    type: int  # 0-文件 1-文件夹
    size: int
    etag: str
    status: int
    category: int  # 0-未知 1-音频 2-视频 3-图片
    trashed: int
    create_at: str
    update_at: int


class Pan123AuthService:
    """123云盘认证服务"""

    API_BASE_OPEN = "https://open-api.123pan.com"  # 开放平台API地址
    API_BASE_WEB = "https://www.123pan.com"  # Web版API地址（用于账号密码登录）
    # 限流控制：令牌获取最小间隔（秒）
    TOKEN_FETCH_MIN_INTERVAL = 5

    def __init__(self, client_id: str = "", client_secret: str = "", username: str = "", password: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._last_token_fetch_time: float = 0
        self._token_lock = asyncio.Lock()  # 用于防止并发获取token

        # 从配置文件加载token
        self._load_token_from_config()

    def _load_token_from_config(self):
        """从配置文件加载token"""
        try:
            from config import get_config
            config = get_config()
            
            # 如果配置中有token且匹配当前认证方式，加载token
            if (config.pan123.access_token and 
                config.pan123.token_expires_at):
                # 检查是否匹配当前认证方式
                auth_match = False
                if self.username and config.pan123.username == self.username:
                    auth_match = True
                elif self.client_id and config.pan123.client_id == self.client_id:
                    auth_match = True
                
                if auth_match:
                    self._access_token = config.pan123.access_token
                    try:
                        self._token_expires_at = datetime.fromisoformat(config.pan123.token_expires_at)
                        logger.debug("从配置文件加载token")
                    except Exception as e:
                        logger.warning(f"解析token过期时间失败: {e}")
                        self._access_token = None
                        self._token_expires_at = None
        except Exception as e:
            logger.debug(f"从配置文件加载token失败: {e}")
            self._access_token = None
            self._token_expires_at = None
    
    def _save_token_to_config(self):
        """保存token到配置文件"""
        try:
            from config import get_config_manager
            config_manager = get_config_manager()
            config = config_manager.get()
            
            # 更新认证信息
            if self.username:
                config.pan123.username = self.username
                config.pan123.password = self.password
                # 清空client信息
                config.pan123.client_id = ""
                config.pan123.client_secret = ""
            elif self.client_id:
                config.pan123.client_id = self.client_id
                config.pan123.client_secret = self.client_secret
                # 清空用户名密码
                config.pan123.username = ""
                config.pan123.password = ""
            
            # 更新token信息
            config.pan123.access_token = self._access_token
            if self._token_expires_at:
                config.pan123.token_expires_at = self._token_expires_at.isoformat()
            else:
                config.pan123.token_expires_at = None
            
            # 保存配置
            config_manager.save()
            logger.debug("token已保存到配置文件")
        except Exception as e:
            logger.warning(f"保存token到配置文件失败: {e}")

    async def get_access_token(self) -> str:
        """获取访问令牌"""
        # 检查是否已有有效token
        if self._is_token_valid():
            return self._access_token

        # 使用锁防止并发获取token
        async with self._token_lock:
            # 再次检查，可能在等待锁的过程中已经被其他协程获取了
            if self._is_token_valid():
                return self._access_token

            # 检查距离上次获取token的时间间隔
            current_time = time.time()
            time_since_last_fetch = current_time - self._last_token_fetch_time
            if time_since_last_fetch < self.TOKEN_FETCH_MIN_INTERVAL:
                wait_time = self.TOKEN_FETCH_MIN_INTERVAL - time_since_last_fetch
                logger.debug(f"等待 {wait_time:.2f} 秒后获取token（限流）")
                await asyncio.sleep(wait_time)

            # 获取新token（带重试机制）
            return await self._fetch_access_token_with_retry()

    async def _fetch_access_token_with_retry(self, max_retries: int = 3, initial_delay: float = 1.0) -> str:
        """从服务器获取新的访问令牌（带重试机制）"""
        last_error = None

        for attempt in range(max_retries):
            try:
                # 如果有用户名密码，使用账号密码登录
                if self.username and self.password:
                    token, expired_at = await self.login_by_account(self.username, self.password)
                    # login_by_account 已经返回带 "Bearer " 前缀的 token
                    self._access_token = token
                    self._token_expires_at = expired_at
                    self._last_token_fetch_time = time.time()

                    # 保存token到配置
                    self._save_token_to_config()

                    logger.debug("使用账号密码成功获取token")
                    return self._access_token
                # 否则使用开放平台API
                elif self.client_id and self.client_secret:
                    url = f"{self.API_BASE_OPEN}/api/v1/access_token"
                    headers = {
                        "Platform": "open_platform",
                        "Content-Type": "application/json"
                    }
                    data = {
                        "clientID": self.client_id,
                        "clientSecret": self.client_secret
                    }

                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(url, json=data, headers=headers)
                        response.raise_for_status()

                        result = response.json()
                        if result.get("code") != 0:
                            error_msg = result.get('message', '未知错误')

                            # 检查是否是频率限制错误
                            if "频繁" in error_msg or "请稍后" in error_msg:
                                if attempt < max_retries - 1:
                                    delay = initial_delay * (2 ** attempt)  # 指数退避
                                    logger.warning(f"获取token触发频率限制（第{attempt + 1}次尝试），等待 {delay:.1f} 秒后重试")
                                    await asyncio.sleep(delay)
                                    continue
                                else:
                                    raise Exception(f"获取访问令牌失败（频率限制）: {error_msg}")
                            else:
                                raise Exception(f"获取访问令牌失败: {error_msg}")

                        data = result["data"]
                        self._access_token = data["accessToken"]
                        self._token_expires_at = datetime.fromisoformat(data["expiredAt"])
                        self._last_token_fetch_time = time.time()

                        # 保存token到配置
                        self._save_token_to_config()

                        logger.info(f"成功获取访问令牌 (尝试次数: {attempt + 1})")
                        return self._access_token

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"获取token超时（第{attempt + 1}次尝试）")
                if attempt < max_retries - 1:
                    await asyncio.sleep(initial_delay * (2 ** attempt))
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"获取token HTTP错误: {e.response.status_code}（第{attempt + 1}次尝试）")
                if attempt < max_retries - 1:
                    await asyncio.sleep(initial_delay * (2 ** attempt))
            except Exception as e:
                # 如果不是"操作频繁"错误，直接抛出
                error_msg = str(e)
                if "频繁" not in error_msg and "请稍后" not in error_msg:
                    raise
                last_error = e
                logger.warning(f"获取token失败: {error_msg}（第{attempt + 1}次尝试）")
                if attempt < max_retries - 1:
                    await asyncio.sleep(initial_delay * (2 ** attempt))

        # 所有重试都失败了
        raise Exception(f"获取访问令牌失败（已重试 {max_retries} 次）: {last_error}")

    def _is_token_valid(self) -> bool:
        """检查token是否有效"""
        if not self._access_token or not self._token_expires_at:
            return False
        # 提前1小时刷新token
        from datetime import timedelta
        return datetime.now() < (self._token_expires_at.replace(tzinfo=None) - timedelta(hours=1))

    def is_token_expired(self) -> bool:
        """检查token是否已过期"""
        return not self._is_token_valid()

    def get_auth_header(self) -> str:
        """获取认证头"""
        token = self._access_token
        if not token:
            raise Exception("访问令牌未初始化，请先调用 get_access_token()")
        # 如果 token 已经包含 "Bearer " 前缀，直接返回；否则添加前缀
        if token.startswith("Bearer "):
            return token
        return f"Bearer {token}"

    @staticmethod
    async def login_by_account(username: str, password: str) -> tuple[str, datetime]:
        """
        使用账号密码登录获取token（静态方法，不需要Client ID/Secret）
        使用与 123pan_web-main 相同的 Android 客户端登录方式

        Args:
            username: 用户名/手机号
            password: 密码

        Returns:
            tuple: (token, expired_at) 或抛出异常
        """
        import requests
        import uuid

        # 使用 Android 客户端协议登录（与 123pan_web-main 相同）
        headers = {
            "user-agent": "123pan/v2.4.0(12;Xiaomi)",
            "authorization": "",
            "accept-encoding": "gzip",
            "content-type": "application/json",
            "osversion": "12",
            "loginuuid": str(uuid.uuid4().hex),
            "platform": "android",
            "devicetype": "MI-ONE PLUS",
            "devicename": "Xiaomi",
            "host": "www.123pan.com",
            "app-version": "61",
            "x-app-version": "2.4.0"
        }

        # data 必须作为 JSON 发送
        data = {"type": 1, "passport": username, "password": password}

        try:
            logger.info(f"尝试使用 Android 客户端登录: {username}")
            login_url = f"{Pan123AuthService.API_BASE_WEB}/b/api/user/sign_in"

            response = requests.post(
                login_url,
                headers=headers,
                json=data,
                timeout=10
            )

            logger.info(f"登录响应状态码: {response.status_code}")
            logger.info(f"登录响应内容: {response.text[:500]}")

            if response.status_code != 200:
                raise Exception(f"登录失败: HTTP {response.status_code} - {response.text}")

            result = response.json()
            if result.get("code") != 200:
                raise Exception(f"登录失败: {result.get('message', '未知错误')}")

            token = result["data"]["token"]
            # token 需要 "Bearer " 前缀
            full_token = f"Bearer {token}"
            # 设置过期时间为30天后
            expired_at = Pan123AuthService._get_expired_time(30)

            logger.info(f"登录成功，token: {token[:20]}...")
            return full_token, expired_at

        except requests.Timeout:
            raise Exception("登录超时，请检查网络连接")
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}, 响应内容: {response.text[:1000]}")
            raise Exception("登录失败: 服务器返回的数据格式错误，请检查账号密码是否正确")
        except Exception as e:
            raise Exception(f"登录失败: {str(e)}")

    @staticmethod
    def _get_expired_time(days: int) -> datetime:
        """
        获取过期时间

        Args:
            days: 天数

        Returns:
            datetime: 过期时间
        """
        from datetime import timedelta
        return datetime.now() + timedelta(days=days)


class Pan123FolderService:
    """123云盘文件夹管理服务"""

    API_BASE = "https://open-api.123pan.com"

    def __init__(self, auth_service: Pan123AuthService, user_id: str = None):
        self.auth = auth_service
        self.user_id = user_id or "global"  # 默认使用全局用户ID

    async def find_folder(self, name: str, parent_id: int = 0) -> Optional[int]:
        """查找文件夹，返回文件夹ID，如果不存在返回None
        
        Args:
            name: 文件夹名称
            parent_id: 父目录ID
        """
        files = await self.list_files(parent_id, limit=100)
        for file in files:
            # type=1 表示文件夹, trashed=0 表示不在回收站
            if file.type == 1 and file.trashed == 0 and file.filename == name:
                # 验证文件夹 ID 是否有效（尝试列出该文件夹的文件）
                try:
                    test_files = await self.list_files(file.file_id, limit=1)
                    logger.info(f"从API找到文件夹: {name}, ID: {file.file_id}")
                    return file.file_id
                except Exception as e:
                    # 如果列出文件失败，说明文件夹 ID 可能无效
                    logger.warning(f"文件夹 {name} (ID: {file.file_id}) 可能已失效: {e}")
                    return None

        return None

    async def search_files(self, keyword: str, search_mode: int = 1, limit: int = 100) -> List[FileInfo]:
        """全局搜索文件
        Args:
            keyword: 搜索关键字
            search_mode: 搜索模式，0=全文模糊搜索，1=精准搜索
            limit: 每页文件数量
        """
        url = f"{self.API_BASE}/api/v2/file/list"
        headers = {
            "Authorization": self.auth.get_auth_header(),
            "Platform": "open_platform",
            "Content-Type": "application/json"
        }
        params = {
            "parentFileId": 0,  # 搜索时会被 searchData 参数覆盖
            "limit": limit,
            "searchData": keyword,
            "searchMode": search_mode
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers)
            result = response.json()

            if result.get("code") == 0:
                files = []
                for item in result["data"]["fileList"]:
                    files.append(FileInfo(
                        file_id=item["fileId"],
                        filename=item["filename"],
                        parent_file_id=item["parentFileId"],
                        type=item["type"],
                        size=item["size"],
                        etag=item.get("etag", ""),
                        status=item["status"],
                        category=item.get("category", 0),
                        trashed=item["trashed"],
                        create_at=item["createAt"],
                        update_at=item["updateAt"]
                    ))
                return files
            else:
                raise Exception(f"搜索文件失败: {result.get('message')}")

    async def create_folder(self, name: str, parent_id: int = 0, check_exists: bool = True) -> int:
        """创建文件夹，返回文件夹ID (dirID)

        Args:
            name: 文件夹名称
            parent_id: 父目录ID
            check_exists: 是否检查文件夹是否已存在，如果存在则返回现有文件夹ID
        """
        # 在开始操作前统一检查并刷新token（如果需要），避免多次刷新
        if self.auth.is_token_expired():
            logger.debug(f"Token 已过期，提前刷新以避免 API 调用失败")
            await self.auth.get_access_token()

        # 如果启用检查，先查找是否已存在
        if check_exists:
            existing_folder_id = await self.find_folder(name, parent_id)
            if existing_folder_id is not None:
                return existing_folder_id

        max_retries = 1  # 只重试1次，用于处理极端情况下的同步问题

        for attempt in range(max_retries):
            url = f"{self.API_BASE}/upload/v1/file/mkdir"
            headers = {
                "Authorization": self.auth.get_auth_header(),
                "Platform": "open_platform",
                "Content-Type": "application/json"
            }
            data = {
                "name": name,
                "parentID": parent_id
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=data, headers=headers)
                result = response.json()

                if result.get("code") == 0:
                    dir_id = result["data"]["dirID"]
                    logger.info(f"创建文件夹成功: {name}, ID: {dir_id}")
                    return dir_id
                else:
                    # 如果是因为文件夹已存在而失败，尝试查找
                    error_msg = result.get("message", "")

                    # 极端情况下可能出现同步问题，此时再刷新一次token
                    if "token is expired" in error_msg.lower() or "token expired" in error_msg.lower():
                        if attempt < max_retries - 1:
                            logger.warning(f"Token 在刷新后仍然过期（极端情况），再次刷新并重试 (尝试 {attempt + 1}/{max_retries})")
                            await self.auth.get_access_token()
                            continue

                    if ("已存在" in error_msg or "重名" in error_msg or "duplicate" in error_msg.lower() or
                        "同名文件夹" in error_msg or "无法进行创建" in error_msg):
                        logger.warning(f"创建文件夹失败（已存在）: {error_msg}，尝试重新查找")
                        # 尝试查找已存在的文件夹（直接API查询）
                        existing_folder_id = await self.find_folder(name, parent_id)
                        if existing_folder_id is not None:
                            logger.info(f"找到已存在的文件夹: {name}, ID: {existing_folder_id}")
                            return existing_folder_id

                        # 如果 find_folder 也失败了（可能是因为 list_files 验证失败），再尝试一次不带验证的查找
                        try:
                            files = await self.list_files(parent_id, limit=100)
                            for file in files:
                                if file.type == 1 and file.trashed == 0 and file.filename == name:
                                    logger.info(f"找到已存在的文件夹（无验证）: {name}, ID: {file.file_id}")
                                    return file.file_id
                        except Exception as retry_error:
                            logger.warning(f"尝试查找现有文件夹失败: {retry_error}")

                    raise Exception(f"创建文件夹失败: {error_msg}")

    async def list_files(self, parent_id: int = 0, limit: int = 100) -> List[FileInfo]:
        """获取文件列表（单次请求，最大100条）"""
        # 提前检查并刷新token（如果需要）
        if self.auth.is_token_expired():
            logger.debug(f"Token 已过期，提前刷新以避免 list_files 失败")
            await self.auth.get_access_token()

        max_retries = 1  # 只重试1次，用于处理极端情况

        for attempt in range(max_retries):
            url = f"{self.API_BASE}/api/v2/file/list"
            headers = {
                "Authorization": self.auth.get_auth_header(),
                "Platform": "open_platform",
                "Content-Type": "application/json"
            }
            params = {
                "parentFileId": parent_id,
                "limit": limit
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, headers=headers)
                result = response.json()

                if result.get("code") == 0:
                    files = []
                    for item in result["data"]["fileList"]:
                        files.append(FileInfo(
                            file_id=item["fileId"],
                            filename=item["filename"],
                            parent_file_id=item["parentFileId"],
                            type=item["type"],
                            size=item["size"],
                            etag=item.get("etag", ""),
                            status=item["status"],
                            category=item.get("category", 0),
                            trashed=item["trashed"],
                            create_at=item["createAt"],
                            update_at=item["updateAt"]
                        ))
                    return files
                else:
                    error_msg = result.get('message', '')
                    # 极端情况下可能出现同步问题，此时再刷新一次token
                    if "token is expired" in error_msg.lower() or "token expired" in error_msg.lower():
                        if attempt < max_retries - 1:
                            logger.warning(f"Token 在刷新后仍然过期（极端情况），再次刷新并重试 (尝试 {attempt + 1}/{max_retries})")
                            await self.auth.get_access_token()
                            continue
                    raise Exception(f"获取文件列表失败: {error_msg}")

    async def list_all_files(self, parent_id: int = 0) -> List[FileInfo]:
        """获取文件列表（分批加载所有文件，使用last_file_id分页）"""
        all_files = []
        page_size = 100
        last_file_id = None

        while True:
            url = f"{self.API_BASE}/api/v2/file/list"
            headers = {
                "Authorization": self.auth.get_auth_header(),
                "Platform": "open_platform",
                "Content-Type": "application/json"
            }
            params = {
                "parentFileId": parent_id,
                "limit": page_size
            }

            # 添加last_file_id参数用于分页
            if last_file_id is not None:
                params["lastFileId"] = last_file_id

            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, headers=headers)
                result = response.json()

                if result.get("code") == 0:
                    file_list = result["data"].get("fileList", [])

                    if not file_list:
                        break

                    # 转换为FileInfo对象
                    for item in file_list:
                        all_files.append(FileInfo(
                            file_id=item["fileId"],
                            filename=item["filename"],
                            parent_file_id=item["parentFileId"],
                            type=item["type"],
                            size=item["size"],
                            etag=item.get("etag", ""),
                            status=item["status"],
                            category=item.get("category", 0),
                            trashed=item["trashed"],
                            create_at=item["createAt"],
                            update_at=item["updateAt"]
                        ))

                    # 如果获取的文件数小于每页大小，说明已经加载完所有文件
                    if len(file_list) < page_size:
                        break

                    # 使用最后一个文件的ID作为下一页的起始点
                    last_file_id = file_list[-1]["fileId"]
                else:
                    raise Exception(f"获取文件列表失败: {result.get('message')}")

        return all_files

    async def get_file_detail(self, file_id: int) -> Optional[FileInfo]:
        """获取文件详情"""
        url = f"{self.API_BASE}/api/v1/file/detail"
        headers = {
            "Authorization": self.auth.get_auth_header(),
            "Platform": "open_platform",
            "Content-Type": "application/json"
        }
        params = {"fileID": file_id}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers)
            result = response.json()

            if result.get("code") == 0:
                data = result["data"]
                return FileInfo(
                    file_id=data["fileID"],
                    filename=data["filename"],
                    parent_file_id=data["parentFileID"],
                    type=data["type"],
                    size=data["size"],
                    etag=data["etag"],
                    status=data["status"],
                    category=data.get("category", 0),
                    trashed=data["trashed"],
                    create_at=data["createAt"],
                    update_at=0
                )
            return None

    async def trash_files(self, file_ids: List[int]) -> bool:
        """将文件/文件夹移至回收站"""
        url = f"{self.API_BASE}/api/v1/file/trash"
        headers = {
            "Authorization": self.auth.get_auth_header(),
            "Platform": "open_platform",
            "Content-Type": "application/json"
        }
        data = {
            "fileIDs": file_ids
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, headers=headers)
            result = response.json()

            if result.get("code") == 0:
                logger.info(f"文件已移至回收站: {file_ids}")
                return True
            else:
                error_msg = result.get("message", "未知错误")
                logger.error(f"移至回收站失败: {error_msg}")
                raise Exception(f"移至回收站失败: {error_msg}")


class Pan123DownloadService:
    """123云盘离线下载管理服务"""

    API_BASE = "https://open-api.123pan.com"

    def __init__(self, auth_service: Pan123AuthService):
        self.auth = auth_service

    async def create_download_task(
        self,
        url: str,
        dir_id: int,
        file_name: Optional[str] = None
    ) -> int:
        """创建离线下载任务，返回任务ID (taskID)"""
        # 提前检查并刷新token（如果需要）
        if self.auth.is_token_expired():
            logger.debug(f"Token 已过期，提前刷新以避免 create_download_task 失败")
            await self.auth.get_access_token()

        max_retries = 1  # 只重试1次，用于处理极端情况

        for attempt in range(max_retries):
            api_url = f"{self.API_BASE}/api/v1/offline/download"
            headers = {
                "Authorization": self.auth.get_auth_header(),
                "Platform": "open_platform",
                "Content-Type": "application/json"
            }
            data = {
                "url": url,
                "dirID": dir_id
            }
            if file_name:
                data["fileName"] = file_name

            async with httpx.AsyncClient() as client:
                response = await client.post(api_url, json=data, headers=headers)
                result = response.json()

                if result.get("code") == 0:
                    task_id = result["data"]["taskID"]
                    logger.info(f"创建离线下载任务成功: {url}, 任务ID: {task_id}")
                    return task_id
                else:
                    error_message = result.get('message', '未知错误')

                    # 极端情况下可能出现同步问题，此时再刷新一次token
                    if "token is expired" in error_message.lower() or "token expired" in error_message.lower():
                        if attempt < max_retries - 1:
                            logger.warning(f"Token 在刷新后仍然过期（极端情况），再次刷新并重试 (尝试 {attempt + 1}/{max_retries})")
                            await self.auth.get_access_token()
                            continue

                    # 如果是"下载任务重复"错误，尝试查询已有的任务
                    if "重复" in error_message or "duplicate" in error_message.lower():
                        logger.warning(f"下载任务可能已存在: {url}, 尝试查询已有任务...")
                        # 尝试从下载任务列表中查找
                        existing_task_id = await self._find_existing_download_task(url, dir_id)
                        if existing_task_id:
                            logger.info(f"找到已存在的下载任务: {url}, 任务ID: {existing_task_id}")
                            return existing_task_id
                        else:
                            logger.warning(f"未找到已存在的下载任务，但云盘返回重复错误: {url}")
                            # 即使找不到，也抛出异常，但提示更友好
                            raise Exception(f"下载任务可能已存在: {error_message}")
                    else:
                        raise Exception(f"创建离线下载任务失败: {error_message}")
    
    async def _find_existing_download_task(self, url: str, dir_id: int) -> Optional[int]:
        """查找已存在的下载任务"""
        try:
            # 查询下载任务列表
            api_url = f"{self.API_BASE}/api/v1/offline/download/list"
            headers = {
                "Authorization": self.auth.get_auth_header(),
                "Platform": "open_platform",
                "Content-Type": "application/json"
            }
            params = {
                "page": 1,
                "pageSize": 100  # 查询最近100个任务
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(api_url, params=params, headers=headers)
                result = response.json()
                
                if result.get("code") == 0:
                    tasks = result.get("data", {}).get("list", [])
                    # 查找匹配URL和目录ID的任务
                    for task in tasks:
                        if task.get("url") == url and task.get("dirID") == dir_id:
                            return task.get("taskID")
                return None
        except Exception as e:
            logger.debug(f"查询已有下载任务失败: {e}")
            return None

    async def get_download_progress(self, task_id: int) -> Dict:
        """获取下载进度"""
        url = f"{self.API_BASE}/api/v1/offline/download/process"
        headers = {
            "Authorization": self.auth.get_auth_header(),
            "Platform": "open_platform",
            "Content-Type": "application/json"
        }
        params = {"taskID": task_id}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers)
            result = response.json()

            if result.get("code") == 0:
                return {
                    "progress": result["data"]["process"],
                    "status": result["data"]["status"]  # 0进行中、1失败、2成功、3重试中
                }
            else:
                raise Exception(f"获取下载进度失败: {result.get('message')}")

    async def cancel_download_task(self, task_id: int) -> bool:
        """取消下载任务（123云盘API可能不支持，这里保留接口）"""
        # 123云盘暂未提供取消下载任务的API
        logger.warning(f"123云盘暂不支持取消下载任务: {task_id}")
        return False


class Pan123FileService:
    """123云盘文件操作服务"""

    API_BASE = "https://open-api.123pan.com"

    def __init__(self, auth_service: Pan123AuthService):
        self.auth = auth_service

    async def rename_file(self, file_id: int, new_name: str) -> bool:
        """重命名单个文件"""
        url = f"{self.API_BASE}/api/v1/file/name"
        headers = {
            "Authorization": self.auth.get_auth_header(),
            "Platform": "open_platform",
            "Content-Type": "application/json"
        }
        data = {
            "fileId": file_id,
            "fileName": new_name
        }

        async with httpx.AsyncClient() as client:
            response = await client.put(url, json=data, headers=headers)
            result = response.json()

            if result.get("code") == 0:
                logger.info(f"文件重命名成功: {file_id} -> {new_name}")
                return True
            else:
                logger.error(f"文件重命名失败: {result.get('message')}")
                return False

    async def batch_rename(self, rename_list: List[Tuple[int, str]]) -> Dict:
        """批量重命名文件，最多30个"""
        url = f"{self.API_BASE}/api/v1/file/rename"
        headers = {
            "Authorization": self.auth.get_auth_header(),
            "Platform": "open_platform",
            "Content-Type": "application/json"
        }
        # 格式: ["fileId|newName", ...]
        rename_list_str = [f"{fid}|{name}" for fid, name in rename_list]
        data = {"renameList": rename_list_str}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, headers=headers)
            result = response.json()

            if result.get("code") == 0:
                logger.info(f"批量重命名成功: {len(rename_list_str)} 个文件")
                return {
                    "success_count": len(rename_list_str),
                    "fail_count": 0
                }
            else:
                logger.error(f"批量重命名失败: {result.get('message')}")
                return {
                    "success_count": 0,
                    "fail_count": len(rename_list_str),
                    "message": result.get("message")
                }


class Pan123AndroidFolderService:
    """123云盘文件夹管理服务 - 使用 Android 客户端 API（无需开发者权益包）"""

    API_BASE = "https://www.123pan.com"

    def __init__(self, auth_service: Pan123AuthService):
        self.auth = auth_service

    def _get_android_headers(self) -> dict:
        """获取 Android 客户端请求头"""
        return {
            "user-agent": "123pan/v2.4.0(12;Xiaomi)",
            "authorization": self.auth.get_auth_header(),
            "accept-encoding": "gzip",
            "content-type": "application/json",
            "osversion": "12",
            "platform": "android",
            "devicetype": "MI-ONE PLUS",
            "devicename": "Xiaomi",
            "host": "www.123pan.com",
            "app-version": "61",
            "x-app-version": "2.4.0"
        }

    async def list_files(self, parent_id: int = 0, limit: int = 100) -> List[FileInfo]:
        """获取文件列表（单次请求，最大100条）"""
        # 使用 Android 客户端 API
        url = f"{self.API_BASE}/api/file/list/new"
        headers = self._get_android_headers()
        params = {
            "driveId": 0,
            "limit": limit,
            "next": 0,
            "orderBy": "file_id",
            "orderDirection": "desc",
            "parentFileId": str(parent_id),
            "trashed": False,
            "SearchData": "",
            "Page": "1",
            "OnlyLookAbnormalFile": 0,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=30)
            result = response.json()

            if result.get("code") != 0:
                raise Exception(f"获取文件列表失败: {result.get('message', '未知错误')}")

            # 转换数据格式
            info_list = result.get("data", {}).get("InfoList", [])
            files = []
            for item in info_list:
                # Type: 0=文件, 1=文件夹
                file_type = 0 if item.get("Type") == 0 else 1
                files.append(FileInfo(
                    file_id=item.get("FileId", 0),
                    filename=item.get("FileName", ""),
                    parent_file_id=parent_id,
                    type=file_type,
                    size=item.get("Size", 0),
                    etag=item.get("Etag", ""),
                    status=item.get("Status", 1),
                    category=item.get("Category", 0),
                    trashed=0,  # Android API 已经通过 trashed 参数过滤
                    create_at=item.get("CreateAt", ""),
                    update_at=item.get("UpdateAt", 0),
                ))

            return files

    async def list_all_files(self, parent_id: int = 0) -> List[FileInfo]:
        """获取文件列表（分批加载所有文件）"""
        all_files = []
        limit = 100

        # Android API 使用分页，需要循环获取
        page = 1
        while True:
            url = f"{self.API_BASE}/api/file/list/new"
            headers = self._get_android_headers()
            params = {
                "driveId": 0,
                "limit": limit,
                "next": 0,
                "orderBy": "file_id",
                "orderDirection": "desc",
                "parentFileId": str(parent_id),
                "trashed": False,
                "SearchData": "",
                "Page": str(page),
                "OnlyLookAbnormalFile": 0,
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, params=params, timeout=30)
                result = response.json()

                if result.get("code") != 0:
                    raise Exception(f"获取文件列表失败: {result.get('message', '未知错误')}")

                info_list = result.get("data", {}).get("InfoList", [])
                if not info_list:
                    break

                # 转换数据格式
                for item in info_list:
                    file_type = 0 if item.get("Type") == 0 else 1
                    all_files.append(FileInfo(
                        file_id=item.get("FileId", 0),
                        filename=item.get("FileName", ""),
                        parent_file_id=parent_id,
                        type=file_type,
                        size=item.get("Size", 0),
                        etag=item.get("Etag", ""),
                        status=item.get("Status", 1),
                        category=item.get("Category", 0),
                        trashed=0,
                        create_at=item.get("CreateAt", ""),
                        update_at=item.get("UpdateAt", 0),
                    ))

                total = result.get("data", {}).get("Total", 0)
                if len(all_files) >= total:
                    break

                page += 1

        return all_files

    async def find_folder(self, name: str, parent_id: int = 0) -> Optional[int]:
        """查找文件夹，返回文件夹ID，如果不存在返回None"""
        files = await self.list_files(parent_id, limit=100)
        for file in files:
            if file.type == 1 and file.filename == name:
                return file.file_id
        return None

    async def create_folder(self, name: str, parent_id: int = 0, check_exists: bool = True) -> int:
        """创建文件夹，返回文件夹ID

        Args:
            name: 文件夹名称
            parent_id: 父目录ID
            check_exists: 是否检查文件夹是否已存在，如果存在则返回现有文件夹ID
        """
        # 如果启用检查，先查找是否已存在
        if check_exists:
            existing_folder_id = await self.find_folder(name, parent_id)
            if existing_folder_id is not None:
                return existing_folder_id

        # 使用 Android 客户端 API 创建文件夹
        url = f"{self.API_BASE}/a/api/file/upload_request"
        headers = self._get_android_headers()

        data = {
            "driveId": 0,
            "etag": "",
            "fileName": name,
            "parentFileId": parent_id,
            "size": 0,
            "type": 1,  # 1 表示文件夹
            "duplicate": 1,
            "NotReuse": True,
            "event": "newCreateFolder",
            "operateType": 1,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, headers=headers, timeout=30)
            result = response.json()

            if result.get("code") != 0:
                raise Exception(f"创建文件夹失败: {result.get('message', '未知错误')}")

            # 返回创建的文件夹 ID
            return result.get("data", {}).get("fileId", 0)
