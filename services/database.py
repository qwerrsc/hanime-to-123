"""
SQLite数据库服务
提供轻量级数据库操作接口
"""
import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from loguru import logger
from datetime import datetime


class Database:
    """SQLite数据库管理类"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            # 默认使用服务目录下的 data/hanime.db
            from pathlib import Path
            self.db_path = Path(__file__).parent.parent / "data" / "hanime.db"
        else:
            self.db_path = Path(db_path)
        self._ensure_db_dir()
        self._init_database()

    def _ensure_db_dir(self):
        """确保数据库目录存在"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def _init_database(self):
        """初始化数据库表结构"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 创建任务表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    folder_id INTEGER NOT NULL,
                    folder_name TEXT NOT NULL,
                    download_task_id INTEGER,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0.0,
                    file_id INTEGER,
                    desired_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT,
                    download_url TEXT,
                    retry_count INTEGER DEFAULT 0,
                    user_id TEXT
                )
            """)

            # 检查并添加 user_id 列（如果表已存在但没有该列）
            try:
                cursor.execute("ALTER TABLE tasks ADD COLUMN user_id TEXT")
                logger.info("已添加 user_id 列到 tasks 表")
            except sqlite3.OperationalError:
                # 列已存在，忽略错误
                pass



            # 创建配置表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at)")

            # 创建视频信息表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    series_name TEXT,
                    cover_url TEXT,
                    duration TEXT,
                    local_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    user_id TEXT,
                    incomplete INTEGER DEFAULT 0
                )
            """)

            # 添加 series_name 列（如果不存在）
            try:
                cursor.execute("ALTER TABLE videos ADD COLUMN series_name TEXT")
            except sqlite3.OperationalError:
                # 列已存在，忽略错误
                pass

            # 添加 incomplete 列（如果不存在）
            try:
                cursor.execute("ALTER TABLE videos ADD COLUMN incomplete INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                # 列已存在，忽略错误
                pass

            # 添加 rename_name 列（如果不存在）
            try:
                cursor.execute("ALTER TABLE videos ADD COLUMN rename_name TEXT")
            except sqlite3.OperationalError:
                # 列已存在，忽略错误
                pass

            conn.commit()
            logger.info("数据库初始化完成")

    # ========== 任务表操作 ==========

    def get_all_tasks(self, status_filter: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有任务"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status_filter and status_filter != "all":
                if user_id:
                    cursor.execute(
                        "SELECT * FROM tasks WHERE status = ? AND user_id = ? ORDER BY created_at DESC",
                        (status_filter, user_id)
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                        (status_filter,)
                    )
            else:
                if user_id:
                    cursor.execute(
                        "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC",
                        (user_id,)
                    )
                else:
                    cursor.execute("SELECT * FROM tasks ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取单个任务"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_task(self, task_data: Dict[str, Any]) -> bool:
        """创建任务"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO tasks (
                        task_id, video_id, title, folder_id, folder_name,
                        download_task_id, status, progress, file_id, desired_name,
                        created_at, updated_at, error_message, download_url, retry_count, user_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_data["task_id"],
                    task_data["video_id"],
                    task_data["title"],
                    task_data["folder_id"],
                    task_data["folder_name"],
                    task_data.get("download_task_id"),
                    task_data["status"],
                    task_data.get("progress", 0.0),
                    task_data.get("file_id"),
                    task_data.get("desired_name"),
                    task_data["created_at"],
                    task_data["updated_at"],
                    task_data.get("error_message"),
                    task_data.get("download_url"),
                    task_data.get("retry_count", 0),
                    task_data.get("user_id")
                ))
                return True
            except sqlite3.IntegrityError:
                logger.error(f"任务 {task_data['task_id']} 已存在")
                return False

    def update_task(self, task_id: str, update_data: Dict[str, Any]) -> bool:
        """更新任务"""
        if not update_data:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 构建更新语句
            set_clause = ", ".join([f"{k} = ?" for k in update_data.keys()])
            values = list(update_data.values()) + [task_id]
            
            cursor.execute(f"""
                UPDATE tasks SET {set_clause} WHERE task_id = ?
            """, values)
            return cursor.rowcount > 0

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            return cursor.rowcount > 0

    def delete_tasks_by_status(self, status: str, user_id: Optional[str] = None) -> int:
        """根据状态删除任务"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("DELETE FROM tasks WHERE status = ? AND user_id = ?", (status, user_id))
            else:
                cursor.execute("DELETE FROM tasks WHERE status = ?", (status,))
            return cursor.rowcount

    def delete_all_tasks(self, user_id: Optional[str] = None) -> int:
        """删除所有任务"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("DELETE FROM tasks WHERE user_id = ?", (user_id,))
            else:
                cursor.execute("DELETE FROM tasks")
            return cursor.rowcount

    def get_task_statistics(self, user_id: Optional[str] = None) -> Dict[str, int]:
        """获取任务统计"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                        SUM(CASE WHEN status = 'downloading' THEN 1 ELSE 0 END) as downloading,
                        SUM(CASE WHEN status = 'renaming' THEN 1 ELSE 0 END) as renaming,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                    FROM tasks
                    WHERE user_id = ?
                """, (user_id,))
            else:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                        SUM(CASE WHEN status = 'downloading' THEN 1 ELSE 0 END) as downloading,
                        SUM(CASE WHEN status = 'renaming' THEN 1 ELSE 0 END) as renaming,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                    FROM tasks
                """)
            row = cursor.fetchone()
            return dict(row)

    # ========== 系列任务表操作 ==========


    # ========== 配置表操作 ==========

    def get_config(self, key: str, default: Any = None) -> Optional[str]:
        """获取配置值"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_config(self, key: str, value: Any) -> bool:
        """设置配置值"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO config (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, json.dumps(value) if isinstance(value, (dict, list)) else str(value), now))
            return True

    def get_all_config(self) -> Dict[str, str]:
        """获取所有配置"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM config")
            rows = cursor.fetchall()
            return {row["key"]: row["value"] for row in rows}

    # ========== 视频信息表操作 ==========

    def get_all_videos(
        self,
        user_id: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        time_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取视频列表（支持搜索、分页、排序、时间筛选）"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 构建查询条件
            where_conditions = []
            params = []

            if user_id:
                where_conditions.append("user_id = ?")
                params.append(user_id)

            if search:
                # 泛搜索：支持标题、视频ID、系列名称的模糊匹配
                # 支持简繁体互通搜索
                from services.chinese_converter import get_converter
                converter = get_converter()

                # 获取搜索词的所有变体（原文、简体、繁体）
                search_variants = converter.get_search_variants(search)

                # 构建多个 LIKE 条件，用 OR 连接
                like_conditions = []
                for field in ["title", "video_id", "series_name"]:
                    for variant in search_variants:
                        search_pattern = f"%{variant}%"
                        like_conditions.append(f"{field} LIKE ?")
                        params.append(search_pattern)

                # 将所有 LIKE 条件用 OR 连接
                where_conditions.append(f"({' OR '.join(like_conditions)})")

            # 时间筛选（使用created_at字段存储的发布日期）
            if time_filter and time_filter != 'all':
                if time_filter.isdigit() and len(time_filter) == 4:
                    # 年份筛选 (如 "2024")
                    where_conditions.append("strftime('%Y', created_at) = ?")
                    params.append(time_filter)
                elif time_filter.startswith('-'):
                    # 只选择月份，年份为空 (如 "-02" 表示所有年份的2月)
                    where_conditions.append("strftime('%m', created_at) = ?")
                    params.append(time_filter[1:])
                elif '-' in time_filter:
                    # 年月筛选 (如 "2024-11")
                    where_conditions.append("strftime('%Y-%m', created_at) = ?")
                    params.append(time_filter)
                elif time_filter in ['24h', '2d', '1w', '1m', '3m']:
                    # 快捷筛选：最近24小时、2天、1周、1个月、3个月
                    from datetime import timedelta
                    time_map = {
                        '24h': timedelta(hours=24),
                        '2d': timedelta(days=2),
                        '1w': timedelta(weeks=1),
                        '1m': timedelta(days=30),
                        '3m': timedelta(days=90)
                    }
                    delta = time_map.get(time_filter, timedelta(hours=24))
                    threshold_date = (datetime.now() - delta).strftime('%Y-%m-%d')
                    where_conditions.append("date(created_at) >= ?")
                    params.append(threshold_date)

            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

            # 验证排序字段
            valid_sort_fields = ["created_at", "updated_at", "duration"]
            sort_field = sort_by if sort_by in valid_sort_fields else "updated_at"

            # 验证排序方向
            sort_dir = sort_order.upper() if sort_order.upper() in ["ASC", "DESC"] else "DESC"

            # 获取总数
            count_sql = f"SELECT COUNT(*) FROM videos WHERE {where_clause}"
            cursor.execute(count_sql, params)
            total = cursor.fetchone()[0]

            # 获取分页数据
            offset = (page - 1) * page_size
            data_sql = f"""
                SELECT * FROM videos
                WHERE {where_clause}
                ORDER BY {sort_field} {sort_dir}
                LIMIT ? OFFSET ?
            """
            cursor.execute(data_sql, params + [page_size, offset])
            rows = cursor.fetchall()

            return {
                "videos": [dict(row) for row in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }

    def get_video(self, video_id: str) -> Optional[Dict[str, Any]]:
        """获取单个视频"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_or_update_video(self, video_data: Dict[str, Any]) -> bool:
        """创建或更新视频信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # 检查标题是否包含 [中字後補] 标记为不完善
                title = video_data.get("title", "")
                is_incomplete = 1 if "[中字後補]" in title else 0

                # 如果提供了 incomplete 字段，使用提供的值；否则根据标题判断
                incomplete = video_data.get("incomplete", is_incomplete)

                cursor.execute("""
                    INSERT INTO videos (
                        video_id, title, series_name, cover_url, duration, local_url,
                        created_at, updated_at, user_id, incomplete, rename_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET
                        title = excluded.title,
                        series_name = excluded.series_name,
                        cover_url = excluded.cover_url,
                        duration = excluded.duration,
                        local_url = excluded.local_url,
                        updated_at = excluded.updated_at,
                        incomplete = excluded.incomplete,
                        rename_name = excluded.rename_name
                """, (
                    video_data["video_id"],
                    title,
                    video_data.get("series_name"),
                    video_data.get("cover_url"),
                    video_data.get("duration"),
                    video_data.get("local_url"),
                    video_data["created_at"],
                    video_data["updated_at"],
                    video_data.get("user_id"),
                    incomplete,
                    video_data.get("rename_name")
                ))
                return True
            except Exception as e:
                logger.error(f"创建/更新视频信息失败: {e}")
                return False

    def delete_video(self, video_id: str) -> bool:
        """删除视频"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
            return cursor.rowcount > 0

    def update_incomplete_video(self, series_name: str, video_title: str, **update_fields) -> bool:
        """
        更新不完善视频的信息（用于完善视频后更新旧的不完善版本）

        Args:
            series_name: 系列名称
            video_title: 完善版本的标题
            **update_fields: 要更新的字段（title, cover_url, duration, local_url 等）
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # 查找该系列中，标题包含 [中字後補] 的不完善视频
                # 提取系列名称部分（去除序号）
                import re
                series_name_base = re.sub(r'\s+\d+$', '', video_title).strip()
                
                # 查找匹配的不完善视频
                cursor.execute("""
                    SELECT video_id, title, cover_url, duration, local_url, created_at, user_id
                    FROM videos
                    WHERE series_name = ?
                    AND incomplete = 1
                    AND (title LIKE ? OR title LIKE ?)
                    ORDER BY video_id
                """, (series_name, f"{series_name_base}%", f"%{series_name_base}%"))
                
                incomplete_videos = cursor.fetchall()
                updated_count = 0
                
                for video in incomplete_videos:
                    incomplete_title = video['title']
                    # 去除不完善视频标题中的 [中字後補] 标记和多余部分
                    clean_title = re.sub(r'\s*\[中字後補\]\s*', '', incomplete_title).strip()
                    
                    # 构建更新数据
                    update_data = {
                        'incomplete': 0,  # 标记为完善
                        'updated_at': datetime.now().isoformat()  # 更新时间戳
                    }
                    
                    # 更新标题：优先使用提供的 new_title，否则使用清理后的标题
                    if 'title' in update_fields and update_fields['title']:
                        update_data['title'] = update_fields['title']
                    else:
                        update_data['title'] = clean_title
                    
                    # 更新其他字段（如果提供）
                    if 'cover_url' in update_fields:
                        update_data['cover_url'] = update_fields['cover_url']
                    if 'duration' in update_fields:
                        update_data['duration'] = update_fields['duration']
                    if 'local_url' in update_fields:
                        update_data['local_url'] = update_fields['local_url']
                    if 'user_id' in update_fields:
                        update_data['user_id'] = update_fields['user_id']
                    
                    # 注意：保持原有的封面不变，除非明确提供新的封面URL
                    
                    # 构建更新语句
                    set_clause = ", ".join([f"{k} = ?" for k in update_data.keys()])
                    values = list(update_data.values()) + [video['video_id']]
                    
                    cursor.execute(f"""
                        UPDATE videos SET {set_clause}
                        WHERE video_id = ?
                    """, values)
                    updated_count += 1
                
                if updated_count > 0:
                    logger.info(f"已更新 {updated_count} 个不完善视频信息（系列: {series_name}）")
                return updated_count > 0
            except Exception as e:
                logger.error(f"更新不完善视频失败: {e}")
                return False

    def update_video_cover(self, video_id: int, update_data: Dict[str, Any], user_id: str) -> bool:
        """
        更新视频封面信息

        Args:
            video_id: 视频ID
            update_data: 要更新的数据（cover_url, updated_at等）
            user_id: 用户ID
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # 构建更新字段
                set_parts = []
                values = []
                for key, value in update_data.items():
                    set_parts.append(f"{key} = ?")
                    values.append(value)

                # 添加WHERE条件
                values.extend([video_id, user_id])

                query = f"""
                    UPDATE videos
                    SET {', '.join(set_parts)}
                    WHERE video_id = ? AND user_id = ?
                """

                cursor.execute(query, values)
                updated_count = cursor.rowcount

                if updated_count > 0:
                    logger.info(f"已更新视频 {video_id} 的封面信息")
                    return True
                else:
                    logger.warning(f"未找到视频 {video_id} 或用户 {user_id} 无权限")
                    return False
            except Exception as e:
                logger.error(f"更新视频封面失败: {e}")
                return False
    def has_video_cover(self, video_id: int, user_id: str) -> bool:
        """
        检查视频是否有封面

        Args:
            video_id: 视频ID
            user_id: 用户ID

        Returns:
            bool: 是否有封面
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT cover_url
                    FROM videos
                    WHERE video_id = ? AND user_id = ? AND cover_url IS NOT NULL AND cover_url != ''
                """, (video_id, user_id))

                result = cursor.fetchone()
                return result is not None

            except Exception as e:
                logger.error(f"检查视频封面失败: {e}")
                return False
            except Exception as e:
                logger.error(f"更新视频封面失败: {e}")
                return False


# 全局数据库实例
_database: Optional[Database] = None


def get_database() -> Database:
    """获取数据库单例"""
    global _database
    if _database is None:
        _database = Database()
    return _database
