"""
认证中间件和依赖项
用于API的用户认证
"""
from fastapi import Depends, HTTPException, status, Request, Response, Cookie
from fastapi.security import APIKeyHeader
from typing import Optional
from loguru import logger
from services.user_manager import get_user_manager
import secrets
import json
from pathlib import Path


# API密钥认证（用于脚本和服务器通信）
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Session cookie 名称
SESSION_COOKIE_NAME = "hanime_session_id"

# Session文件路径
SESSION_FILE = Path(__file__).parent.parent / "data" / "sessions.json"


def _load_sessions():
    """从文件加载sessions"""
    try:
        if SESSION_FILE.exists():
            with open(SESSION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"加载sessions文件失败: {e}")
    return {}


def _save_sessions(sessions: dict):
    """保存sessions到文件"""
    try:
        SESSION_FILE.parent.mkdir(exist_ok=True)
        with open(SESSION_FILE, 'w', encoding='utf-8') as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存sessions文件失败: {e}")


# 从文件加载sessions
_sessions = _load_sessions()


def create_session(user_id: str, username: str) -> str:
    """创建新的 session"""
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = {
        "user_id": user_id,
        "username": username
    }
    _save_sessions(_sessions)  # 持久化到文件
    logger.debug(f"创建 session: {session_id[:8]}... for user: {username}")
    return session_id


def get_session(session_id: str) -> Optional[dict]:
    """获取 session"""
    return _sessions.get(session_id)


def delete_session(session_id: str) -> bool:
    """删除 session"""
    if session_id in _sessions:
        del _sessions[session_id]
        _save_sessions(_sessions)  # 持久化到文件
        logger.debug(f"删除 session: {session_id[:8]}...")
        return True
    return False


async def get_webui_user(
    request: Request,
    response: Response
) -> Optional[dict]:
    """
    获取当前 Web UI 用户（通过 Session）
    用于 Web UI 路由的依赖注入
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)

    if session_id is None:
        return None

    session = get_session(session_id)

    if session is None:
        return None

    return session


async def require_webui_auth(
    user: Optional[dict] = Depends(get_webui_user)
) -> dict:
    """
    要求 Web UI 必须认证的依赖
    用于需要登录的 Web UI 端点
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要登录"
        )
    return user


def get_webui_user_id(user: Optional[dict] = Depends(get_webui_user)) -> Optional[str]:
    """
    获取当前 Web UI 用户ID
    返回Optional,未登录时返回None
    """
    if user is None:
        return None
    return user["user_id"]


async def get_current_user(
    api_key: Optional[str] = Depends(api_key_header)
) -> Optional[dict]:
    """
    获取当前用户（通过API密钥）
    用于 API 路由的依赖注入（脚本调用）
    """
    if api_key is None:
        # 部分API可能不需要认证（例如登录、注册）
        return None

    user_manager = get_user_manager()
    user = user_manager.get_user_by_api_key(api_key)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的API密钥"
        )

    return user


async def require_auth(user: Optional[dict] = Depends(get_current_user)) -> dict:
    """
    要求必须认证的依赖（API密钥）
    用于需要 API 密钥的端点（脚本调用）
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要API密钥认证"
        )
    return user


def get_user_id(user: dict = Depends(require_auth)) -> str:
    """
    获取当前用户ID（API密钥方式）
    """
    return user["user_id"]


# 同时支持Session和API密钥的认证依赖
async def get_user_id_from_any_source(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header)
) -> Optional[str]:
    """
    从Session或API密钥获取用户ID
    优先使用Session,其次使用API密钥
    返回Optional,未认证时返回None
    """
    # 1. 尝试从Session获取
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session = get_session(session_id)
        if session:
            return session["user_id"]

    # 2. 尝试从API密钥获取
    if api_key:
        user_manager = get_user_manager()
        user = user_manager.get_user_by_api_key(api_key)
        if user:
            return user["user_id"]

    # 都没有,返回None
    return None


async def require_user_id_from_any_source(
    user_id: Optional[str] = Depends(get_user_id_from_any_source)
) -> str:
    """
    要求必须认证(支持Session或API密钥)
    """
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要登录或提供API密钥"
        )
    return user_id
