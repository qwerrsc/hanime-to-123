# Hanime 123云盘下载助手

一个基于 FastAPI 的 Web UI 应用，用于从 Hanime1.me 获取视频信息，通过 123云盘离线下载。
## 目前仍有部分接口使用openapi没有更换
此外注意离线功能下载是会员权益中需要有会员
## 功能特性

- 🌐 **Web UI 界面** - 现代化的 Web 界面，无需安装 GUI 应用
- 👥 **多用户支持** - 支持多用户登录，每个用户独立配置和数据隔离
- 🔐 **双重认证方式** - 支持 Client ID/Secret 和账号密码两种登录方式
- 📥 **视频下载** - 支持单个视频推送离线下载
- 📁 **文件夹管理** - 自动创建年份/月份文件夹结构
- 🔄 **实时监控** - 实时查看任务状态和进度
- 🎨 **视频管理** - 视频总览、搜索、导入导出功能
- ⚙️ **配置管理** - Web 界面配置 123 云盘凭证和服务器设置
- 📊 **日志系统** - 详细的用户操作日志和系统日志
- 🚀 **Docker 支持** - 提供 Docker 部署方案
## 界面展示
1.后台设置
<img width="1334" height="710" alt="QQ截图20260203165056" src="https://github.com/user-attachments/assets/b3fa7d33-d7c8-43f2-81c5-bf0c69427fd3" />
2.脚本推送
<img width="829" height="764" alt="QQ截图20260203165415" src="https://github.com/user-attachments/assets/4f2a986e-a7d6-457b-bec4-9a29a6fdcf0c" />
3.离线下载任务
<img width="1434" height="321" alt="QQ截图20260203165553" src="https://github.com/user-attachments/assets/237662ce-9444-40e9-bf2b-39414ebd51ea" />
4.运行日志
<img width="1410" height="766" alt="QQ截图20260203165601" src="https://github.com/user-attachments/assets/67844273-a0f8-450b-8eda-4cfd61115a6e" />
5.视频总览数据库
<img width="1449" height="933" alt="QQ截图20260203165319" src="https://github.com/user-attachments/assets/17e0ec5c-1c4e-4deb-b2c3-29f0bef13ec3" />
6.封面获取
<img width="538" height="337" alt="QQ截图20260203165123" src="https://github.com/user-attachments/assets/a448189c-4c3e-45e3-9214-eb89e291ae10" />
7.云盘显示
<img width="929" height="579" alt="QQ截图20260203165624" src="https://github.com/user-attachments/assets/e37fbba9-0470-45a0-9a9c-7de15090d31f" />

## 安装
### 前置要求

- Python 3.8+
- pip

### 本地安装

1. 克隆或下载项目：

```bash
git clone <repository-url>
cd hanime-downloader-server
```

2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 确保数据目录存在（程序会自动创建）：

```bash
mkdir -p data logs
```

### Docker 安装

参考 `DOCKER.md` 文件了解详细的 Docker 部署步骤。

## 运行

### 本地运行

启动服务器：

```bash
python main.py
```

服务器启动后，在浏览器中访问：

```
http://127.0.0.1:16544
```

### Docker 运行

```bash
docker-compose up -d
```

## 配置

首次使用需要注册账号并登录 Web 界面，然后在"设置"标签页中配置。
注册admin用户，管理权限在admin用户登陆界面

### 123云盘配置

系统支持两种认证方式，请选择其中一种：

#### 方式一：Client ID / Secret（不推荐目前收费）

1. 访问开发者权益专区购买
2. 获取应用的 Client ID 和 Client Secret
3. 在设置页面切换到 "Client ID/Secret" 标签页并填入这两个值
4. 点击"获取 Token" 测试连接

**注意**：开放平台 API 需要购买开发者权益包，推荐使用方式二。

#### 方式二：账号密码登录（推荐）

1. 切换到"账号密码登录"标签页
2. 填入 123 云盘的用户名/手机号和密码
3. 点击"获取 Token"测试连接

此方式使用 Android 客户端 API，无需购买开发者权益包。

#### 其他配置项

- **云盘文件夹 ID**：文件存储的根目录 ID（默认为 0）
- **选择文件夹**：点击按钮可在文件夹选择器中浏览并选择目录

### 监控配置

- **检查间隔**：任务状态检查间隔（秒），默认 3 秒
- **下载超时**：下载任务超时时间（秒），默认 3600 秒（1 小时）

### API 密钥管理

- 每个用户有独立的 API 密钥，用于油猴脚本验证
- 可以在设置中查看或重新生成 API 密钥
- 重新生成后需要更新油猴脚本中的配置

## 使用说明

### 1. 注册和登录

1. 访问 Web 界面 `http://127.0.0.1:16544`
2. 点击"注册账号"，填写用户名和密码
3. 注册成功后自动登录

### 2. 配置 123云盘

在"设置"标签页中选择认证方式并填写相应信息，然后点击"保存设置"或"获取 Token"测试连接。

### 3. 使用油猴脚本

1. 在浏览器中安装 Tampermonkey 或 Greasemonkey
2. 打开 `Hanime 123云盘下载助手-1.0.2.user.js` 文件
3. 点击脚本右上角的安装按钮
4. 在脚本配置中填入服务器地址和 API 密钥

### 4. 下载视频

1. 访问 hanime1.me 网站
2. 打开要下载的视频播放页面
3. 点击脚本弹出的"推送到服务器"按钮
4. 在 Web 界面中查看任务状态和进度

### 5. 管理任务

Web 界面提供以下标签页：

- **任务列表**：查看所有下载任务，支持按状态筛选、删除任务
- **视频总览**：查看所有下载的视频，支持搜索、时间筛选、导入导出
- **日志**：查看系统运行日志和用户操作日志
- **设置**：配置 123 云盘和服务器参数

## 项目结构

```
hanime-downloader-server/
├── main.py                 # 主程序入口
├── config.py              # 配置管理
├── requirements.txt       # Python 依赖
├── Dockerfile            # Docker 镜像构建文件
├── docker-compose.yml     # Docker Compose 配置
├── api/                  # API 路由
│   ├── server.py         # FastAPI 服务器
│   ├── routes.py         # API 路由定义
│   ├── models.py         # 数据模型
│   ├── auth.py           # 认证中间件
│   └── auth_routes.py   # 认证相关路由
├── services/             # 业务逻辑服务
│   ├── pan123_service.py       # 123云盘 API 服务
│   ├── task_manager.py         # 任务管理
│   ├── monitor_service.py      # 监控服务
│   ├── rename_service.py       # 重命名服务
│   ├── auth_manager.py        # 认证服务管理
│   ├── user_manager.py        # 用户管理
│   ├── database.py            # 数据库服务
│   └── chinese_converter.py   # 中文繁简转换
├── webui/               # Web UI 前端
│   ├── index.html        # 主页面
│   ├── login.html       # 登录页面
│   └── static/          # 静态资源
│       ├── css/         # 样式文件
│       └── js/          # JavaScript 文件
├── data/                # 数据目录
│   ├── hanime.db        # SQLite 数据库
│   └── config.json     # 配置文件（已废弃）
└── logs/                # 日志目录
    └── server.log       # 服务器日志
```

## API 文档

启动服务器后，可以访问：

- **Swagger UI**: `http://127.0.0.1:16544/docs`
- **ReDoc**: `http://127.0.0.1:16544/redoc`

## 数据库

系统使用 SQLite 数据库存储以下数据：

- 用户信息（用户名、密码哈希、API 密钥）
- 用户配置（123云盘凭证、监控设置等）
- 下载任务（任务状态、进度、视频信息等）
- 视频信息（视频详情、系列信息等）
- 操作日志（用户操作记录）

数据库文件位置：`data/hanime.db`

## 注意事项

1. **认证方式选择**：推荐使用账号密码登录方式，无需购买开发者权益包
2. **网络访问**：服务器默认监听 `0.0.0.0:16544`，可从局域网访问
3. **Token 管理**：系统会自动管理 Token 的获取和刷新，Token 有效期为 30 天
4. **下载监控**：下载任务会自动监控进度，完成后会自动重命名文件
5. **文件夹结构**：系统会自动创建年份/月份文件夹结构来组织下载的视频
6. **多用户隔离**：每个用户的配置、任务和视频数据完全独立

## 油猴脚本配置

脚本配置项：

- **服务器地址**：`http://127.0.0.1:16544`（或局域网 IP 地址）
- **API 密钥**：在 Web 界面设置中获取

## 技术栈

- **后端**：FastAPI, Uvicorn
- **数据库**：SQLite
- **前端**：原生 HTML/CSS/JavaScript
- **HTTP 客户端**：httpx, aiohttp, requests
- **日志**：Loguru

## 许可证

MIT License

## 更新日志

### v2.0.0

- 新增多用户支持
- 新增账号密码登录方式
- 新增视频总览功能
- 新增导入导出功能
- 改进文件夹管理
- 优化认证服务缓存机制
- 支持自动创建年份/月份文件夹结构

### v1.0.0

- 初始版本
- 支持 Client ID/Secret 认证
- 基础下载功能
- Web UI 界面
