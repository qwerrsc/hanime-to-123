"""
FastAPI 服务器
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from loguru import logger
import uvicorn

from api import routes
from api import auth_routes
from config import get_config
from services.monitor_service import MonitorService


# 禁用缓存的静态文件类
class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if isinstance(response, Response):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


# 全局监控服务实例
monitor_service: MonitorService = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global monitor_service

    # 启动时
    config = get_config()
    logger.info(f"启动服务器: {config.server.host}:{config.server.port}")

    # 注意：不在启动时自动验证token，因为现在支持多用户
    # token会在用户首次调用API时按需加载和验证

    # 启动监控服务
    monitor_service = MonitorService()
    asyncio.create_task(monitor_service.start())

    try:
        yield
    except asyncio.CancelledError:
        logger.info("服务器正在关闭...")
        # 不重新抛出,让清理逻辑正常执行
    finally:
        # 关闭时
        logger.info("关闭监控服务")
        if monitor_service:
            try:
                await monitor_service.stop()
            except Exception as e:
                logger.error(f"停止监控服务时出错: {e}")


# UI版本号 (每次更新UI时修改此值)
UI_VERSION = "2.1.5"  # 2026-01-08 - 不完善视频标记和自动删除功能


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    config = get_config()

    app = FastAPI(
        title="Hanime 123云盘下载助手",
        version="1.0.0",
        lifespan=lifespan
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 静态文件服务
    webui_path = Path(__file__).parent.parent / "webui"
    static_path = webui_path / "static"
    covers_path = Path(__file__).parent.parent / "data" / "covers"

    if static_path.exists():
        app.mount("/static", NoCacheStaticFiles(directory=str(static_path)), name="static")

    # 封面图片静态文件服务
    if covers_path.exists():
        covers_path.mkdir(parents=True, exist_ok=True)
        app.mount("/covers", NoCacheStaticFiles(directory=str(covers_path)), name="covers")
    else:
        covers_path.mkdir(parents=True, exist_ok=True)
        app.mount("/covers", NoCacheStaticFiles(directory=str(covers_path)), name="covers")
    
    # Web UI 路由
    @app.get("/")
    async def index():
        """返回Web UI首页"""
        index_file = webui_path / "index.html"
        if index_file.exists():
            return FileResponse(
                str(index_file),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "X-UI-Version": UI_VERSION  # 添加UI版本头
                }
            )
        return {"message": "Web UI not found"}

    @app.get("/login.html")
    async def login():
        """返回登录页"""
        login_file = webui_path / "login.html"
        if login_file.exists():
            return FileResponse(
                str(login_file),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "X-UI-Version": UI_VERSION  # 添加UI版本头
                }
            )
        return {"message": "Login page not found"}

    @app.get("/folder-picker.html")
    async def folder_picker():
        """返回文件夹选择页面"""
        picker_file = webui_path / "folder-picker.html"
        if picker_file.exists():
            return FileResponse(
                str(picker_file),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
        return {"message": "Folder picker page not found"}

    # 注册API路由
    app.include_router(routes.router)
    app.include_router(auth_routes.router)

    # 添加UI版本检查API
    @app.get("/api/ui-version")
    async def get_ui_version():
        """获取当前UI版本"""
        return {"version": UI_VERSION}

    # 添加全局异常处理器，捕获验证错误
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """处理请求验证错误"""
        errors = exc.errors()
        error_details = []
        for error in errors:
            error_details.append({
                "field": ".".join(str(loc) for loc in error.get("loc", [])),
                "message": error.get("msg"),
                "type": error.get("type"),
                "input": error.get("input")
            })
        logger.error(f"请求验证失败: {error_details}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": error_details,
                "message": "请求数据验证失败"
            }
        )

    return app


# 全局服务器实例
_server: uvicorn.Server = None
_server_loop: asyncio.AbstractEventLoop = None
_server_task: Optional[asyncio.Task] = None


async def run_server(host: str = "127.0.0.1", port: int = 8000):
    """运行服务器"""
    global _server, _server_loop, _server_task
    app = create_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    _server = uvicorn.Server(config)
    _server_loop = asyncio.get_running_loop()
    _server_task = asyncio.create_task(_server.serve())
    try:
        await _server_task
    except asyncio.CancelledError:
        logger.info("服务器任务已取消")
        # 不重新抛出，让服务器正常关闭


def get_monitor_service() -> Optional[MonitorService]:
    """获取监控服务实例"""
    global monitor_service
    return monitor_service


async def stop_server():
    """停止监控服务（不停止HTTP服务器）"""
    global monitor_service
    if monitor_service:
        logger.info("正在停止监控服务...")
        try:
            await monitor_service.stop()
            logger.info("监控服务已停止")
        except Exception as e:
            logger.error(f"停止监控服务失败: {e}")
            raise


async def start_server():
    """启动监控服务"""
    global monitor_service
    if monitor_service and monitor_service._running:
        logger.warning("监控服务已在运行")
        return
    
    logger.info("正在启动监控服务...")
    if not monitor_service:
        monitor_service = MonitorService()
    await monitor_service.start()
    logger.info("监控服务已启动")


if __name__ == "__main__":
    import asyncio
    config = get_config()
    asyncio.run(run_server(config.server.host, config.server.port))
