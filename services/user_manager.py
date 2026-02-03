"""
用户管理服务
负责用户登录、注册、会话管理
"""
import hashlib
import secrets
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from loguru import logger


class UserManager:
    """用户管理器"""

    def __init__(self):
        from services.database import get_database
        self.db = get_database()
        self._init_users_table()

    def _init_users_table(self):
        """初始化用户表"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 创建用户表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    api_key TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    last_login TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)

            # 创建用户配置表（每个用户的独立配置）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    config_key TEXT NOT NULL,
                    config_value TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, config_key),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_configs_user_id ON user_configs(user_id)")

            conn.commit()
            logger.info("用户表初始化完成")

    def _hash_password(self, password: str) -> str:
        """密码哈希"""
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def _generate_api_key(self) -> str:
        """生成API密钥"""
        return secrets.token_urlsafe(32)

    def register_user(self, username: str, password: str) -> Dict[str, Any]:
        """注册用户"""
        # 检查用户名是否已存在
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                return {
                    "success": False,
                    "message": "用户名已存在"
                }

        # 生成用户ID和API密钥
        user_id = secrets.token_urlsafe(16)
        api_key = self._generate_api_key()
        password_hash = self._hash_password(password)
        now = datetime.now().isoformat()

        # 创建用户
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (user_id, username, password_hash, api_key, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, username, password_hash, api_key, now))

            conn.commit()
            logger.info(f"用户注册成功: {username}")

        # 创建默认配置（复制全局配置）
        self._init_user_config(user_id)

        # 为用户添加日志handler
        try:
            from api.user_logger import add_user_log_handler
            add_user_log_handler(user_id)
            user_logger = logger.bind(user_id=user_id)
            user_logger.info(f"用户 {username} (ID: {user_id}) 注册成功")
        except Exception as e:
            logger.warning(f"创建用户日志handler失败: {e}")

        return {
            "success": True,
            "user_id": user_id,
            "api_key": api_key,
            "message": "用户创建成功"
        }

    def login_user(self, username: str, password: str) -> Dict[str, Any]:
        """用户登录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 先检查用户是否存在
            cursor.execute("""
                SELECT user_id, username, password_hash, api_key, is_active
                FROM users
                WHERE username = ?
            """, (username,))

            row = cursor.fetchone()

            if not row:
                logger.warning(f"登录失败: 用户不存在 - {username}")
                return {"success": False, "error": "user_not_found", "message": "用户不存在"}

            # 检查用户是否被禁用
            if not row["is_active"]:
                logger.warning(f"登录失败: 用户已被禁用 - {username}")
                return {"success": False, "error": "user_disabled", "message": "用户已被禁用"}

            # 验证密码
            password_hash = self._hash_password(password)
            if password_hash != row["password_hash"]:
                logger.warning(f"登录失败: 密码错误 - {username}")
                return {"success": False, "error": "wrong_password", "message": "密码错误"}

            # 更新最后登录时间
            now = datetime.now().isoformat()
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE user_id = ?",
                (now, row["user_id"])
            )
            conn.commit()

            logger.info(f"用户登录成功: {username}")

            # 确保用户日志handler存在，并记录登录日志
            try:
                from api.user_logger import add_user_log_handler
                add_user_log_handler(row["user_id"])
                user_logger = logger.bind(user_id=row["user_id"])
                user_logger.info(f"用户 {username} 登录成功")
            except Exception as e:
                logger.warning(f"记录用户登录日志失败: {e}")

            return {
                "success": True,
                "user_id": row["user_id"],
                "username": row["username"],
                "api_key": row["api_key"]
            }

    def get_user_by_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """通过API密钥获取用户"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, username, is_active
                FROM users
                WHERE api_key = ? AND is_active = 1
            """, (api_key,))

            row = cursor.fetchone()
            return dict(row) if row else None

    def regenerate_api_key(self, user_id: str, password: str) -> Optional[Dict[str, Any]]:
        """重新生成API密钥"""
        # 验证密码
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            password_hash = self._hash_password(password)

            cursor.execute("""
                SELECT user_id, username FROM users
                WHERE user_id = ? AND password_hash = ?
            """, (user_id, password_hash))

            row = cursor.fetchone()
            if not row:
                return None

            # 生成新的API密钥
            new_api_key = self._generate_api_key()

            cursor.execute(
                "UPDATE users SET api_key = ? WHERE user_id = ?",
                (new_api_key, user_id)
            )
            conn.commit()

            logger.info(f"用户 {row['username']} 重新生成API密钥")

            return {
                "success": True,
                "api_key": new_api_key,
                "message": "API密钥已更新"
            }

    def get_all_users(self) -> list:
        """获取所有用户（管理员功能）"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, username, created_at, last_login, is_active
                FROM users
                ORDER BY created_at DESC
            """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def _init_user_config(self, user_id: str):
        """初始化用户配置（从全局配置复制）"""
        from config import get_config_manager
        config_manager = get_config_manager()
        global_config = config_manager.get().to_dict()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            for section_name, section_data in global_config.items():
                for key, value in section_data.items():
                    # 跳过 token 相关的配置，这些不应该从全局配置复制
                    if key in ['access_token', 'token_expires_at']:
                        continue

                    config_key = f"{section_name}.{key}"
                    cursor.execute("""
                        INSERT OR REPLACE INTO user_configs (user_id, config_key, config_value, updated_at)
                        VALUES (?, ?, ?, ?)
                    """, (user_id, config_key, json.dumps(value) if isinstance(value, (dict, list)) else str(value), now))

            conn.commit()
            logger.info(f"用户 {user_id} 默认配置已初始化")

    def get_user_config(self, user_id: str) -> Dict[str, Any]:
        """获取用户配置"""
        config = {}

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT config_key, config_value
                FROM user_configs
                WHERE user_id = ?
            """, (user_id,))

            rows = cursor.fetchall()

            for row in rows:
                try:
                    # 尝试解析为JSON，失败则直接使用字符串值
                    try:
                        value = json.loads(row["config_value"])
                    except json.JSONDecodeError:
                        value = row["config_value"]

                    # 解析配置键 (例如: pan123.client_id)
                    parts = row["config_key"].split(".", 1)
                    if len(parts) == 2:
                        section, key = parts
                        if section not in config:
                            config[section] = {}
                        config[section][key] = value
                    else:
                        config[row["config_key"]] = value
                except Exception as e:
                    logger.warning(f"解析配置值失败: {row['config_key']}, {e}")

        return config

    def update_user_config(self, user_id: str, config_data: Dict[str, Any]) -> bool:
        """更新用户配置"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            for section_name, section_data in config_data.items():
                for key, value in section_data.items():
                    config_key = f"{section_name}.{key}"
                    cursor.execute("""
                        INSERT OR REPLACE INTO user_configs (user_id, config_key, config_value, updated_at)
                        VALUES (?, ?, ?, ?)
                    """, (user_id, config_key, json.dumps(value) if isinstance(value, (dict, list)) else str(value), now))

            conn.commit()
            logger.info(f"用户 {user_id} 配置已更新")
            return True

    def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            success = cursor.rowcount > 0
            conn.commit()

            if success:
                logger.info(f"用户已删除: {user_id}")

            return success


# 全局用户管理器实例
_user_manager: Optional[UserManager] = None


def get_user_manager() -> UserManager:
    """获取用户管理器单例"""
    global _user_manager
    if _user_manager is None:
        _user_manager = UserManager()
    return _user_manager
