# Docker 调试配置说明

本项目已配置好 Docker 调试环境，支持在容器中运行和调试 Python 代码。

## 文件说明

- `Dockerfile` - 调试环境的 Docker 镜像配置
- `Dockerfile.prod` - 生产环境的 Docker 镜像配置
- `docker-compose.yml` - 调试环境的 Docker Compose 配置
- `docker-compose.prod.yml` - 生产环境的 Docker Compose 配置
- `.devcontainer/devcontainer.json` - VS Code Dev Container 配置
- `.vscode/launch.json` - 包含 Docker 调试配置

## 容器配置说明

### 用户权限
- **容器以 root 身份运行**：确保应用具有完整的系统权限
- **目录挂载**：用户目录下的 `.botgo` 子目录会挂载到容器的 `/root/.botgo`

### 目录挂载
- `./src` → `/app/src` (开发时热重载)
- `./data` → `/app/data` (数据持久化)
- `./src/logs` → `/app/logs` (日志文件)
- `~/.botgo` → `/root/.botgo` (用户 .botgo 目录)

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

## .botgo 目录访问

应用可以通过以下路径访问 .botgo 目录中的文件：
- 容器内路径：`/root/.botgo/`
- Python 中访问示例：
  ```python
  import os
  botgo_path = "/root/.botgo"
  # 或者使用环境变量
  botgo_path = os.path.expanduser("~/.botgo")  # 在容器中会解析为 /root/.botgo
  ```

## 调试技巧

1. **热重载**：修改 `src/` 目录下的代码会自动同步到容器
2. **查看日志**：`docker-compose logs -f botgo-app`
3. **进入容器**：`docker exec -it botgo_debug bash`
4. **停止容器**：`docker-compose down`
5. **查看挂载的 .botgo 目录**：`docker exec -it botgo_debug ls -la /root/.botgo`

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

4. **.botgo 目录访问问题**：
   - 确保主机上 `~/.botgo` 目录存在：`mkdir -p ~/.botgo`
   - 检查目录权限：`ls -la ~/.botgo`
   - 验证容器内挂载：`docker exec -it botgo_debug ls -la /root/.botgo`

## 安全注意事项

由于容器以 root 身份运行，请注意：
- 仅在开发和受信任的环境中使用
- 确保不要暴露不必要的端口到公网
- 定期更新基础镜像和依赖包 