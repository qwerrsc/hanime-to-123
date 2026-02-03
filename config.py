"""
配置管理模块
负责加载、保存和管理应用程序配置
使用 SQLite 数据库存储配置
"""
import json
import os
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, asdict, field
from datetime import datetime
from loguru import logger


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 16544
    cors_origins: List[str] = field(default_factory=lambda: ["*"])


@dataclass
class Pan123Config:
    """123云盘配置"""
    client_id: str = ""
    client_secret: str = ""
    username: str = ""
    password: str = ""
    root_dir_id: int = 0
    access_token: str = ""
    token_expires_at: Optional[str] = None


@dataclass
class MonitoringConfig:
    """监控配置"""
    check_interval: int = 3  # 检查间隔（秒）
    max_retries: int = 3
    download_timeout: int = 3600  # 下载超时（秒）


@dataclass
class Config:
    """总配置类"""
    server: ServerConfig = field(default_factory=ServerConfig)
    pan123: Pan123Config = field(default_factory=Pan123Config)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)

    def to_dict(self):
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        """从字典创建配置"""
        # 获取各个部分的配置，使用默认值处理缺失字段
        server_data = data.get("server", {})
        pan123_data = data.get("pan123", {})
        monitoring_data = data.get("monitoring", {})

        # 确保所有必需字段都有默认值
        server_config = ServerConfig(
            host=server_data.get("host", "0.0.0.0"),
            port=server_data.get("port", 18866),
            cors_origins=server_data.get("cors_origins", ["*"])
        )

        pan123_config = Pan123Config(
            client_id=pan123_data.get("client_id", ""),
            client_secret=pan123_data.get("client_secret", ""),
            root_dir_id=pan123_data.get("root_dir_id", 0),
            access_token=pan123_data.get("access_token", ""),
            token_expires_at=pan123_data.get("token_expires_at")
        )

        monitoring_config = MonitoringConfig(
            check_interval=monitoring_data.get("check_interval", 3),
            max_retries=monitoring_data.get("max_retries", 3),
            download_timeout=monitoring_data.get("download_timeout", 3600)
        )

        return cls(
            server=server_config,
            pan123=pan123_config,
            monitoring=monitoring_config
        )


class ConfigManager:
    """配置管理器 - 使用数据库存储"""

    def __init__(self):
        self.config = Config()
        self.load()

    def load(self) -> Config:
        """从数据库加载配置"""
        try:
            from services.database import get_database
            db = get_database()

            # 尝试从数据库加载完整配置
            config_json = db.get_config("app_config")
            if config_json:
                try:
                    data = json.loads(config_json)
                    self.config = Config.from_dict(data)
                    logger.info("从数据库加载配置成功")
                    return self.config
                except json.JSONDecodeError:
                    logger.warning("配置数据格式错误，使用默认配置")
            else:
                logger.info("数据库中未找到配置，使用默认配置")

            # 使用默认配置并保存到数据库
            self.config = Config()
            self.save()
            return self.config

        except Exception as e:
            logger.error(f"加载配置失败，使用默认配置: {e}")
            self.config = Config()
            return self.config

    def save(self) -> bool:
        """保存配置到数据库"""
        try:
            from services.database import get_database
            db = get_database()
            db.set_config("app_config", self.config.to_dict())
            logger.info("配置已保存到数据库")
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False

    def update(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self.save()

    def get(self) -> Config:
        """获取当前配置"""
        return self.config


# 全局配置实例
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取配置管理器单例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config() -> Config:
    """获取当前配置"""
    return get_config_manager().get()


def get_user_config(user_id: str) -> Config:
    """获取用户配置"""
    from services.user_manager import get_user_manager
    user_manager = get_user_manager()
    user_config_data = user_manager.get_user_config(user_id)

    # 将用户配置转换为 Config 对象
    return Config.from_dict(user_config_data)
