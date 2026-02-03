"""
用户认证相关的API路由
"""
from fastapi import APIRouter, HTTPException, status, Response, Request
from loguru import logger

from api.models import (
    UserRegisterRequest,
    UserLoginRequest,
    UserLoginResponse,
    UserRegenerateApiKeyRequest,
    UserRegenerateApiKeyResponse,
    UserInfo,
    UsersListResponse
)
from services.user_manager import get_user_manager
from api.auth import create_session, delete_session, SESSION_COOKIE_NAME

router = APIRouter(prefix="/api/auth")


@router.post("/register", response_model=UserLoginResponse)
async def register_user(request: UserRegisterRequest, response: Response):
    """注册新用户"""
    try:
        user_manager = get_user_manager()

        # 检查是否已有用户（第一个用户自动成为管理员）
        all_users = user_manager.get_all_users()
        is_first_user = len(all_users) == 0

        result = user_manager.register_user(request.username, request.password)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])

        # 创建 session
        session_id = create_session(result["user_id"], request.username)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=False,  # 开发环境设为 False，生产环境应为 True
            samesite="lax",
            max_age=30 * 24 * 60 * 60  # 30天
        )

        return UserLoginResponse(
            success=True,
            user_id=result["user_id"],
            username=request.username,
            api_key=result["api_key"],
            message="注册成功，请保存API密钥"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册用户失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login", response_model=UserLoginResponse)
async def login_user(request: UserLoginRequest, response: Response):
    """用户登录"""
    try:
        user_manager = get_user_manager()
        result = user_manager.login_user(request.username, request.password)

        if not result.get("success"):
            # 根据错误类型返回不同的错误信息
            error_message = result.get("message", "登录失败")
            raise HTTPException(
                status_code=401,
                detail=error_message
            )

        user = result

        # 创建 session
        session_id = create_session(user["user_id"], user["username"])
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=False,  # 开发环境设为 False，生产环境应为 True
            samesite="lax",
            max_age=30 * 24 * 60 * 60  # 30天
        )

        return UserLoginResponse(
            success=True,
            user_id=user["user_id"],
            username=user["username"],
            api_key=user["api_key"],
            message="登录成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"用户登录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/regenerate-api-key", response_model=UserRegenerateApiKeyResponse)
async def regenerate_api_key(request: UserRegenerateApiKeyRequest):
    """重新生成API密钥"""
    try:
        user_manager = get_user_manager()
        result = user_manager.regenerate_api_key(request.user_id, request.password)

        if not result:
            raise HTTPException(
                status_code=401,
                detail="用户ID或密码错误"
            )

        return UserRegenerateApiKeyResponse(
            success=True,
            api_key=result["api_key"],
            message="API密钥已更新"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新生成API密钥失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users", response_model=UsersListResponse)
async def list_users():
    """获取所有用户列表（需要管理员权限，暂时开放）"""
    try:
        user_manager = get_user_manager()
        users = user_manager.get_all_users()

        user_list = []
        for user in users:
            user_list.append(UserInfo(
                user_id=user["user_id"],
                username=user["username"],
                created_at=user["created_at"],
                last_login=user.get("last_login"),
                is_active=bool(user["is_active"])
            ))

        return UsersListResponse(
            users=user_list,
            total=len(user_list)
        )

    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/logout")
async def logout_user(request: Request, response: Response):
    """用户登出"""
    # 获取 session_id
    session_id = request.cookies.get(SESSION_COOKIE_NAME)

    # 删除 session
    if session_id:
        delete_session(session_id)

    # 清除 cookie
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"success": True, "message": "登出成功"}
