# Hanime 123云盘下载助手 - Docker 部署指南

## 快速启动

### 1. 构建镜像

```bash
docker build -t hanime-downloader:latest .
```

### 2. 启动容器

```bash
docker compose up -d
```

或使用 docker run：

```bash
docker run -d \
  --name hanime-downloader \
  -p 16544:16544 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  hanime-downloader:latest
```

### 3. 访问服务

打开浏览器访问：`http://localhost:16544`

## 配置说明

### 环境变量

在 `docker-compose.yml` 中可以配置以下环境变量：

```yaml
environment:
  - SERVER_HOST=0.0.0.0
  - SERVER_PORT=16544
```

### 数据持久化

容器默认将以下目录挂载到宿主机：

- `/app/data` - 存储用户配置、数据库等
- `/app/logs` - 存储日志文件

## 常用操作

### 查看日志

```bash
docker logs -f hanime-downloader
```

### 进入容器

```bash
docker exec -it hanime-downloader bash
```

### 停止服务

```bash
docker-compose down
```

或：

```bash
docker stop hanime-downloader
```

### 重启服务

```bash
docker-compose restart
```

或：

```bash
docker restart hanime-downloader
```

### 更新镜像

```bash
# 停止并删除旧容器
docker-compose down

# 重新构建镜像
docker build -t hanime-downloader:latest .

# 启动新容器
docker-compose up -d
```

### 清理数据

⚠️ **警告：以下操作会删除所有数据！**

```bash
# 停止容器
docker-compose down

# 删除数据目录（谨慎操作）
rm -rf data/* logs/*

# 重新启动
docker-compose up -d
```

## 端口映射

默认端口为 `16544`，如果需要修改，编辑 `docker-compose.yml`：

```yaml
ports:
  - "8080:16544"  # 将容器的16544端口映射到宿主机的8080端口
```

## 网络访问

### 本地访问

```
http://localhost:16544
```

### 局域网访问

```
http://<你的局域网IP>:16544
```

例如：`http://192.168.1.100:16544`

## 常见问题

### 1. 容器无法启动

检查端口是否被占用：

```bash
# Windows
netstat -ano | findstr :16544

# Linux/Mac
lsof -i :16544
```

如果端口被占用，修改 `docker-compose.yml` 中的端口映射。

### 2. 数据丢失

确保正确挂载了数据卷：

```yaml
volumes:
  - ./data:/app/data
  - ./logs:/app/logs
```

### 3. 权限问题（Linux）

如果遇到权限问题，可以设置正确的权限：

```bash
chmod -R 755 data logs
```

### 4. 镜像构建失败

确保 Dockerfile 和 requirements.txt 在同一目录下，并且有足够的权限：

```bash
# Windows（以管理员身份运行）
# Linux/Mac（使用 sudo）
sudo docker build -t hanime-downloader:latest .
```

## 性能优化

### 资源限制

可以在 `docker-compose.yml` 中添加资源限制：

```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 2G
    reservations:
      cpus: '1'
      memory: 1G
```

### 日志管理

限制容器日志大小：

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

## 备份与恢复

### 备份

```bash
# 停止容器
docker-compose down

# 备份数据目录
tar -czf hanime-backup-$(date +%Y%m%d).tar.gz data/ logs/

# 重新启动
docker-compose up -d
```

### 恢复

```bash
# 停止容器
docker-compose down

# 恢复数据
tar -xzf hanime-backup-20240101.tar.gz

# 重新启动
docker-compose up -d
```

## 生产环境部署建议

1. **使用 HTTPS**：建议使用 Nginx 反向代理并配置 SSL 证书
2. **定期备份**：设置定时任务自动备份数据
3. **监控日志**：使用日志管理工具如 ELK 或 Loki
4. **更新及时**：定期更新镜像以获取最新功能和安全修复

## 技术支持

如遇到问题，请检查：

1. Docker 版本是否满足要求（Docker 20.10+）
2. 端口是否正确映射
3. 数据目录是否有正确的权限
4. 查看容器日志排查具体错误
