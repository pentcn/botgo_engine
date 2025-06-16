# Docker 调试配置说明

本项目已配置好 Docker 调试环境，支持在容器中运行和调试 Python 代码。

## 文件说明

- `Dockerfile` - 调试环境的 Docker 镜像配置
- `Dockerfile.prod` - 生产环境的 Docker 镜像配置
- `docker-compose.yml` - 调试环境的 Docker Compose 配置
- `docker-compose.prod.yml` - 生产环境的 Docker Compose 配置
- `.devcontainer/devcontainer.json` - VS Code Dev Container 配置
- `.vscode/launch.json` - 包含 Docker 调试配置

## 调试方法

### 方法1：远程调试（推荐）

1. **启动调试容器**：
   ```bash
   docker-compose up --build
   ```

2. **在 Cursor 中设置断点**：
   - 在需要调试的 Python 文件中设置断点

3. **开始调试**：
   - 按 `F5` 或打开调试面板
   - 选择 `Docker: 远程调试` 配置
   - 调试器会自动连接到容器

### 方法2：Dev Container 调试

1. **安装 Dev Containers 扩展**（如果使用 VS Code）

2. **在容器中重新打开项目**：
   - `Ctrl+Shift+P` → `Dev Containers: Reopen in Container`

3. **容器内直接调试**：
   - 选择 `Docker: 容器内调试` 配置

## 生产环境运行

```bash
# 使用生产配置运行
docker-compose -f docker-compose.prod.yml up --build -d
```

## 调试技巧

1. **热重载**：修改 `src/` 目录下的代码会自动同步到容器
2. **查看日志**：`docker-compose logs -f botgo-app`
3. **进入容器**：`docker exec -it botgo_debug bash`
4. **停止容器**：`docker-compose down`

## 端口说明

- `5678` - Python 调试端口
- 如有 Web 服务，可在 docker-compose.yml 中添加对应端口映射

## 故障排除

1. **调试连接失败**：
   - 确保容器正在运行：`docker ps`
   - 检查端口是否被占用：`netstat -an | grep 5678`

2. **代码修改不生效**：
   - 检查 volume 挂载是否正确
   - 重启容器：`docker-compose restart`

3. **依赖包问题**：
   - 重新构建镜像：`docker-compose up --build --force-recreate` 