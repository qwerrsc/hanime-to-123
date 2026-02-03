"""
认证服务管理器
用于管理多个用户的认证服务实例，避免重复获取token
"""
from typing import Optional, Dict
from services.pan123_service import Pan123AuthService
from config import get_config
from services.user_manager import get_user_manager
from loguru import logger


class AuthManager:
    """认证服务管理器（支持多用户）"""

    _instance: Optional['AuthManager'] = None
    _auth_services: Dict[str, Pan123AuthService] = {}  # {user_id: auth_service}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_user_config(self, user_id: Optional[str]) -> dict:
        """获取用户配置或全局配置"""
        if user_id:
            user_manager = get_user_manager()
            user_config = user_manager.get_user_config(user_id)
            global_config = get_config()

            # 合并用户配置和全局配置（用户配置优先）
            pan123_config = user_config.get("pan123", {})
            return {
                "client_id": pan123_config.get("client_id", global_config.pan123.client_id),
                "client_secret": pan123_config.get("client_secret", global_config.pan123.client_secret),
                "username": pan123_config.get("username", global_config.pan123.username),
                "password": pan123_config.get("password", global_config.pan123.password),
                "access_token": pan123_config.get("access_token", global_config.pan123.access_token),
                "token_expires_at": pan123_config.get("token_expires_at", global_config.pan123.token_expires_at)
            }
        else:
            config = get_config()
            return {
                "client_id": config.pan123.client_id,
                "client_secret": config.pan123.client_secret,
                "username": config.pan123.username,
                "password": config.pan123.password,
                "access_token": config.pan123.access_token,
                "token_expires_at": config.pan123.token_expires_at
            }

    async def get_auth_service(self, user_id: Optional[str] = None, force_refresh: bool = False) -> Pan123AuthService:
        """获取认证服务实例（支持多用户）

        Args:
            user_id: 用户ID，如果提供则获取该用户的认证服务，否则使用全局配置
            force_refresh: 是否强制刷新缓存（清除旧的认证服务实例）
        """
        config = self._get_user_config(user_id)

        # 检查是否有任何一种认证方式配置
        if not config["client_id"] and not config["client_secret"] and not config["access_token"] and not (config["username"] and config["password"]):
            raise Exception("123云盘未配置，请先配置 Client ID/Secret 或使用账号密码登录")

        # 生成缓存键（user_id为None时使用'global'）
        cache_key = user_id if user_id else "global"

        # 如果强制刷新，清除缓存
        if force_refresh and cache_key in self._auth_services:
            del self._auth_services[cache_key]
            logger.debug(f"清除认证服务缓存 (user_id: {user_id or 'global'})")

        # 检查是否需要创建新实例
        if cache_key not in self._auth_services:
            # 创建认证服务实例（支持账号密码登录）
            self._auth_services[cache_key] = Pan123AuthService(
                client_id=config["client_id"] or "",
                client_secret=config["client_secret"] or "",
                username=config["username"] or "",
                password=config["password"] or ""
            )
            logger.debug(f"创建新的认证服务实例 (user_id: {user_id or 'global'})")

            # 如果配置中已有token，直接设置到实例中（避免重新获取）
            if config["access_token"]:
                try:
                    auth_service = self._auth_services[cache_key]
                    auth_service._access_token = config["access_token"]
                    # 解析过期时间（如果有）
                    if config["token_expires_at"]:
                        from datetime import datetime
                        auth_service._token_expires_at = datetime.fromisoformat(config["token_expires_at"])
                    logger.debug(f"从配置加载token (user_id: {user_id or 'global'})")
                except Exception as e:
                    logger.debug(f"加载token失败: {e}")

        auth_service = self._auth_services[cache_key]

        # 只在有 client_id/secret 时才尝试刷新token
        if config["client_id"] and config["client_secret"] and not auth_service._is_token_valid():
            try:
                await auth_service.get_access_token()
            except Exception as e:
                # 只在不是"频繁"错误时才记录警告
                if "频繁" not in str(e) and "请稍后" not in str(e):
                    logger.warning(f"刷新token失败 (user_id: {user_id or 'global'}): {e}")
                # 即使刷新失败，也返回实例，让具体业务逻辑处理
        elif not config["client_id"] and not config["client_secret"]:
            # 只有 access_token 但没有 client_id/secret，且token已过期
            if not auth_service._is_token_valid():
                raise Exception("Access Token 已过期，请在设置页面配置 Client ID 和 Client Secret 后点击\"获取Token\"")

        # 如果有用户ID，保存更新后的token到用户配置（只在必要时保存）
        # 添加跟踪标记，避免频繁保存
        if user_id and user_id != "global":
            save_key = f'_token_saved_{user_id}'
            # 检查距离上次保存是否超过 5 分钟
            import time
            if (not hasattr(self, save_key) or 
                time.time() - getattr(self, save_key) > 300):
                # 检查是否需要更新配置
                if not config["access_token"] or auth_service.is_token_expired():
                    try:
                        user_manager = get_user_manager()
                        user_manager.update_user_config(user_id, {
                            "pan123": {
                                "access_token": auth_service._access_token,
                                "token_expires_at": auth_service._token_expires_at.isoformat() if auth_service._token_expires_at else None
                            }
                        })
                        setattr(self, save_key, time.time())
                    except Exception as e:
                        # 保存失败不影响主流程
                        pass

        return auth_service

    async def validate_and_refresh_token(self, user_id: Optional[str] = None) -> bool:
        """校验并刷新token（启动时调用）

        Args:
            user_id: 用户ID，如果提供则验证该用户的token，否则验证全局配置
        """
        config = self._get_user_config(user_id)

        if not config["client_id"] or not config["client_secret"]:
            logger.warning("123云盘未配置，无法校验token")
            return False

        try:
            # 创建认证服务实例
            auth_service = Pan123AuthService(
                client_id=config["client_id"],
                client_secret=config["client_secret"]
            )

            # 获取token（如果无效会自动获取新的）
            await auth_service.get_access_token()

            # 缓存实例
            cache_key = user_id if user_id else "global"
            self._auth_services[cache_key] = auth_service

            logger.info(f"token校验成功 (user_id: {user_id or 'global'})")
            return True
        except Exception as e:
            logger.error(f"token校验失败 (user_id: {user_id or 'global'}): {e}")
            return False

    def clear(self, user_id: Optional[str] = None):
        """清除认证服务实例

        Args:
            user_id: 用户ID，如果提供则清除该用户的认证服务，否则清除所有
        """
        if user_id:
            cache_key = user_id if user_id else "global"
            if cache_key in self._auth_services:
                del self._auth_services[cache_key]
                logger.debug(f"清除认证服务实例 (user_id: {user_id or 'global'})")
        else:
            self._auth_services.clear()
            logger.debug("清除所有认证服务实例")


# 全局实例
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    """获取认证服务管理器单例"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager
