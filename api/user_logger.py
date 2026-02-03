"""
用户日志工具
每个用户拥有独立的日志文件
"""
from pathlib import Path
from loguru import logger
import os

# 确保用户日志目录存在
_user_logs_dir = Path(__file__).parent.parent / "logs"
_user_logs_dir.mkdir(exist_ok=True)

# 已添加的用户handler集合（存储handler_id）
_added_user_handlers = {}  # {user_id: handler_id}


def get_user_logger(user_id: str):
    """获取用户专属的logger实例"""
    user_log_file = _user_logs_dir / f"user_{user_id}.log"

    # 为每个用户创建独立的logger
    user_logger = logger.bind(user_id=user_id)

    # 检查是否已经添加过这个用户的handler
    # 这里我们使用一个简单的标记：检查日志文件是否存在
    # 实际使用时，用户应该在每次需要记录日志时调用这个函数

    return user_logger


def add_user_log_handler(user_id: str):
    """为用户添加日志handler（只添加一次）"""
    global _added_user_handlers

    # 检查是否已经有这个handler
    if user_id in _added_user_handlers:
        logger.debug(f"用户日志handler已存在: {user_id}")
        return  # 已经存在，不重复添加

    user_log_file = _user_logs_dir / f"user_{user_id}.log"

    logger.debug(f"准备添加用户日志handler: {user_id}, 文件: {user_log_file}")

    # 添加用户专属的日志handler
    handler_id = logger.add(
        user_log_file,
        rotation="10 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        filter=lambda record: record["extra"].get("user_id") == user_id,
        enqueue=True  # 添加 enqueue=True 确保日志异步写入
    )

    # 记录已添加的handler（保存handler_id）
    _added_user_handlers[user_id] = handler_id
    logger.debug(f"添加用户日志handler: {user_id}, 文件: {user_log_file}, handler_id: {handler_id}")



def remove_user_log_handler(user_id: str):
    """移除用户的日志handler"""
    global _added_user_handlers

    # 检查是否有该用户的handler
    if user_id not in _added_user_handlers:
        logger.debug(f"用户日志handler不存在: {user_id}")
        return

    # 获取handler_id
    handler_id = _added_user_handlers[user_id]

    try:
        # 使用logger.remove()关闭handler并释放文件句柄
        logger.remove(handler_id)
        logger.info(f"已移除用户日志handler: {user_id}, handler_id: {handler_id}")
    except Exception as e:
        logger.warning(f"移除用户日志handler时出错: {e}")
    finally:
        # 从字典中移除记录
        _added_user_handlers.pop(user_id, None)


def delete_user_log(user_id: str):
    """删除用户的日志文件"""
    # 先移除 handler 以释放文件句柄
    remove_user_log_handler(user_id)

    # 给系统一点时间释放文件句柄
    import time
    time.sleep(0.1)

    user_log_file = _user_logs_dir / f"user_{user_id}.log"
    if user_log_file.exists():
        # 尝试删除文件，如果失败则重试几次
        max_retries = 3
        for i in range(max_retries):
            try:
                os.remove(user_log_file)
                logger.info(f"删除用户日志文件: {user_id}")
                return
            except PermissionError as e:
                if i < max_retries - 1:
                    time.sleep(0.2)
                    continue
                else:
                    # 最后一次尝试失败，记录错误
                    logger.warning(f"无法删除用户日志文件（可能仍在使用）: {user_id}, 错误: {e}")
                    raise
    else:
        logger.debug(f"用户日志文件不存在: {user_id}")


def get_user_log_file(user_id: str) -> Path:
    """获取用户的日志文件路径"""
    return _user_logs_dir / f"user_{user_id}.log"


def ensure_user_log_handler(user_id: str):
    """确保用户日志handler存在（如果不存在则添加）"""
    add_user_log_handler(user_id)
