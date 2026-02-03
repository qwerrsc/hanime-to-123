"""
主程序入口
"""
import sys
import asyncio
from pathlib import Path
from loguru import logger

# 确保数据目录存在
project_dir = Path(__file__).parent
data_dir = project_dir / "data"
logs_dir = project_dir / "logs"
data_dir.mkdir(exist_ok=True)
logs_dir.mkdir(exist_ok=True)

# 配置日志
logger.add(
    logs_dir / "server.log",
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
)
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


def main():
    """主函数"""
    from config import get_config
    from api.server import run_server
    
    config = get_config()
    logger.info(f"启动 Hanime 123云盘下载助手 Web UI")
    logger.info(f"服务器地址: http://{config.server.host}:{config.server.port}")
    logger.info(f"请在浏览器中访问上述地址：本地输入127.0.0.1，局域网输入局域网IP地址")
    
    try:
        asyncio.run(run_server(config.server.host, config.server.port))
    except KeyboardInterrupt:
        logger.info("服务器已停止")
    except asyncio.CancelledError:
        logger.info("服务器已停止")
    except Exception as e:
        logger.error(f"服务器运行出错: {e}")
        raise
        raise


if __name__ == "__main__":
    main()
