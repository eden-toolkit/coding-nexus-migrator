# CODING Maven 制品库迁移工具

用于将 CODING 制品库中的 Maven 依赖批量迁移到 Nexus 仓库。

## 🚀 核心特性

- **🔄 内存流水线迁移** - 边下载边上传，零磁盘占用，高性能传输
- **🎯 智能去重机制** - 基于文件哈希避免重复上传，支持断点续传
- **⚡ 稳定限速迁移** - 针对 CODING 30 req/s 限制优化，多线程并发处理
- **📦 自动版本识别** - 智能识别 SNAPSHOT 和 RELEASE 版本，自动分配到对应仓库
- **🔧 灵活配置方式** - 支持配置文件、环境变量、混合模式
- **📊 详细进度监控** - 实时显示迁移进度和统计信息

## 📋 系统要求

- Python 3.7+
- CODING 账户和 API Token
- Nexus 仓库访问权限

## 🎯 快速开始

### 本地开发环境

#### 1. 安装依赖
```bash
pip install -r requirements.txt
```

#### 2. 创建配置文件
```bash
python main.py init-config
cp config.sample.yaml config.yaml
```

#### 3. 编辑配置
编辑 `config.yaml`，填入您的配置信息：
```yaml
# CODING 配置
coding:
  token: "your_coding_token_here"
  team_id: 123456
  maven_repositories:
    your-repo-name:
      username: "your_username"
      password: "your_password"

# Nexus 配置
nexus:
  url: "http://localhost:8081"
  username: "admin"
  password: "admin123"
  release_repo: "maven-releases"
  snapshot_repo: "maven-snapshots"

# 迁移配置
migration:
  project_names:
    - "your_project_name"
```

#### 4. 执行迁移
```bash
# 测试连接
python main.py test-connections

# 查看可用项目
python main.py list-projects

# 执行迁移（内存流水线模式）
python main.py migrate-memory-pipeline your_project_name
```

### 服务器部署

#### 1. 构建分发包
```bash
pip install build
python -m build
```

#### 2. 上传并安装
将 `dist/coding_nexus_migrator-1.0.0-py3-none-any.whl` 上传到服务器：
```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装工具
pip install coding_nexus_migrator-1.0.0-py3-none-any.whl
```

#### 3. 配置（三种方式）

**方式一：配置文件**
```bash
cp config.sample.yaml config.yaml
vi config.yaml
```

**方式二：环境变量（推荐生产环境）**
```bash
export CODING_TOKEN="your_token"
export CODING_TEAM_ID="your_team_id"
export NEXUS_URL="http://nexus:8081"
export NEXUS_USERNAME="user"
export NEXUS_PASSWORD="password"
```

**方式三：混合模式**
```bash
cp .env.template .env
vi .env
source .env
```

#### 4. 运行迁移
```bash
# 验证配置
cnm --config config.yaml verify-config

# 执行迁移
cnm --config config.yaml migrate --projects your_project

# 后台运行
nohup cnm --config config.yaml migrate --projects your_project > migration.log 2>&1 &
```

## 🔧 详细配置

### 配置文件完整示例

```yaml
# CODING 配置
coding:
  token: "your_coding_token"
  team_id: 123456

  # Maven 仓库认证配置（支持多仓库）
  maven_repositories:
    repo-releases:
      username: "releases-user"
      password: "releases-pass"
    repo-snapshots:
      username: "snapshots-user"
      password: "snapshots-pass"

  # Maven 包过滤配置
  maven_filter:
    enabled: true
    patterns:
      - "com.yourcompany.*"
      - "org.yourorg.*"

  # 性能优化配置
  performance:
    max_workers: 12      # 并发工作线程数
    batch_size: 50       # 批处理大小
    memory_limit_mb: 100 # 内存使用限制

  # 分页限制配置
  pagination:
    page_size: 100       # 每页获取的包数量
    max_pages: 50        # 最大页数限制

  # 速率限制配置
  rate_limit:
    requests_per_second: 25  # 请求速率限制

# Nexus 配置
nexus:
  url: "http://localhost:8081"
  username: "admin"
  password: "admin123"
  release_repo: "maven-releases"
  snapshot_repo: "maven-snapshots"

# 迁移配置
migration:
  project_names:          # 要迁移的项目列表
    - "project1"
    - "project2"
  download_path: "./target/downloads"  # 仅标准模式使用
  batch_size: 500
  parallel_downloads: 10

# 日志配置
logging:
  level: "INFO"
  file: "target/migration.log"
  max_size_mb: 10        # 日志文件最大大小
  backup_count: 5        # 保留备份文件数量
```

### 环境变量支持

支持以下环境变量覆盖配置文件：

| 环境变量 | 对应配置 | 说明 |
|---------|---------|------|
| `CODING_TOKEN` | `coding.token` | CODING API Token |
| `CODING_TEAM_ID` | `coding.team_id` | CODING 团队ID |
| `NEXUS_URL` | `nexus.url` | Nexus 服务器URL |
| `NEXUS_USERNAME` | `nexus.username` | Nexus 用户名 |
| `NEXUS_PASSWORD` | `nexus.password` | Nexus 密码 |
| `NEXUS_REPOSITORY` | `nexus.release_repo` | Release 仓库名 |
| `NEXUS_SNAPSHOT_REPOSITORY` | `nexus.snapshot_repo` | Snapshot 仓库名 |

## 📋 命令行接口

### 开发环境命令

```bash
# 配置管理
python main.py init-config                                    # 创建示例配置文件

# 信息查询
python main.py test-connections                              # 测试连接
python main.py list-projects                                 # 列出 CODING 项目
python main.py repository-info                               # 查看 Nexus 仓库信息

# 迁移命令
python main.py migrate-memory-pipeline PROJECT_NAME          # 内存流水线迁移（推荐）
python main.py migrate-pipeline PROJECT_NAME                 # 流水线迁移
python main.py migrate PROJECT_NAME [--standard-mode]        # 标准迁移
python main.py migrate-all [--cleanup]                       # 迁移所有项目
```

### 服务器部署命令（安装后）

```bash
# 全局选项
# --config, -c: 指定配置文件路径（默认：config.yaml）
# --verbose, -v: 详细输出模式

# 配置管理
cnm init-config --output my-config.yaml                       # 创建示例配置文件
cnm --config config.yaml verify-config                       # 验证配置

# 信息查询
cnm --config config.yaml list-projects                       # 列出 CODING 项目
cnm --config config.yaml repository-info                     # 查看 Nexus 仓库信息

# 迁移命令
cnm --config config.yaml migrate --projects PROJECT_NAME     # 内存流水线迁移（默认）
cnm --config config.yaml migrate --projects PROJECT_NAME \
  --standard-mode                                           # 标准模式迁移
cnm --config config.yaml migrate                             # 迁移所有配置的项目
```

### 常用选项

| 选项 | 说明 |
|------|------|
| `--projects, -p` | 指定项目，多个项目用逗号分隔 |
| `--standard-mode` | 使用标准模式（下载到本地再上传） |
| `--dry-run` | 试运行，只查看不执行 |
| `--cleanup` | 迁移完成后清理下载文件（仅标准模式） |
| `--keep-records` | 保留迁移记录文件 |
| `--filter, -f` | 包过滤规则，覆盖配置文件设置 |

### 使用示例

```bash
# 迁移单个项目
cnm --config config.yaml migrate --projects myproject

# 迁移多个项目
cnm --config config.yaml migrate --projects "project1,project2"

# 使用包过滤
cnm --config config.yaml migrate --projects myproject \
  --filter "com.company.*,com.org.*"

# 试运行查看将要迁移的制品
cnm --config config.yaml migrate --projects myproject --dry-run

# 标准模式迁移（适合调试）
cnm --config config.yaml migrate --projects myproject --standard-mode
```

## 🔄 迁移模式说明

### 内存流水线模式（默认推荐）

**特点**：
- ✅ **零磁盘占用** - 文件直接在内存中传输
- ✅ **边下载边上传** - 流水线处理，提高效率
- ✅ **智能去重** - 基于文件哈希避免重复上传
- ✅ **即时清理** - 上传成功后立即释放内存
- ✅ **断点续传** - 支持中断后继续迁移

**使用场景**：磁盘空间有限、追求最高性能

### 标准模式

**特点**：
- 💾 先下载到本地磁盘，再上传到 Nexus
- 🔄 支持文件检查和手动干预
- 📁 可在下载目录查看所有文件

**使用场景**：需要检查文件、调试问题

## 🎯 SNAPSHOT 和 RELEASE 版本处理

工具会自动识别 Maven 制品的版本类型并分配到相应的 Nexus 仓库：

### 版本识别规则

- **SNAPSHOT 版本**：版本号以 `-SNAPSHOT` 结尾（不区分大小写）
  - 例如：`1.0.0-SNAPSHOT`、`2.1.0-snapshot`、`3.0-SNAPSHOT`

- **RELEASE 版本**：所有非 SNAPSHOT 版本
  - 例如：`1.0.0`、`2.1.0`、`3.0.0.RELEASE`

### 仓库检测机制

1. **配置文件指定**：优先使用配置文件中的仓库配置
2. **自动检测**：自动检测 Nexus 中的 Maven 仓库
3. **默认仓库**：如果检测失败，使用配置的默认仓库

## ⚡ 性能优化

### CODING API 限制处理

- **智能速率限制**：自动检测 CODING 的 30 次每秒的限制
- **并发控制**：默认 12 个并发工作线程
- **自动重试**：遇到限流时智能等待重试

### 内存管理

- **内存使用限制**：默认最大 100MB 内存使用
- **流式处理**：边下载边上传，不积累文件在内存中
- **即时清理**：上传成功后立即释放内存

### 低内存服务器优化

对于内存受限的服务器（< 2GB），建议配置：

```yaml
# 低内存优化配置
coding:
  performance:
    max_workers: 1        # 减少并发线程
    memory_limit_mb: 256  # 降低内存限制
    batch_size: 10        # 减小批处理大小

  pagination:
    page_size: 10         # 减小分页大小

  rate_limit:
    requests_per_second: 3  # 降低请求速率
```

运行时优化：
```bash
export PYTHONOPTIMIZE=1
export PYTHONDONTWRITEBYTECODE=1
cnm --config low-memory-config.yaml migrate --projects your_project
```

## 🔍 故障排除

### 常见问题

#### 1. 连接测试失败
**问题**：`CODING connection test failed`

**解决方案**：
- 检查 CODING API Token 是否正确
- 检查团队 ID 是否正确
- 确认网络连接正常

#### 2. 内存使用过高
**问题**：内存使用超过限制

**解决方案**：
- 调整 `performance.max_workers` 参数
- 调整 `performance.batch_size` 参数
- 使用标准模式：`--standard-mode`

#### 3. 上传失败（422 错误）
**问题**：Nexus 上传返回 422 错误

**解决方案**：
- 检查 Nexus 仓库权限配置
- 确认仓库类型是否正确（maven2）
- 检查 Maven 坐标格式

#### 4. 速率限制
**问题**：CODING API 返回速率限制错误

**解决方案**：
- 工具会自动处理，无需手动干预
- 如仍有问题，可降低 `max_workers` 数量

### 日志文件

程序运行时会生成日志文件并自动轮转：

**日志轮转配置**：
- **文件路径**: `target/migration.log`
- **单个文件最大**: 10MB（可配置）
- **保留备份**: 5个文件（可配置）

**文件命名规则**：
```
target/migration.log        # 当前日志文件
target/migration.log.1      # 第1个备份
target/migration.log.2      # 第2个备份
...
```

## 📁 项目结构

```
src/coding_migrator/
├── __init__.py                   # 包初始化
├── models.py                     # 数据模型
├── config.py                     # 配置管理（支持环境变量）
├── cli.py                        # 命令行接口
├── coding_client.py              # CODING API 客户端
├── downloader.py                 # 制品下载器
├── nexus_uploader.py             # Nexus 上传器
├── migrator.py                   # 主迁移器
├── memory_pipeline_migrator.py   # 内存流水线迁移器
├── pipeline_migrator.py          # 流水线迁移器
├── exceptions.py                 # 自定义异常
└── utils.py                      # 工具函数

# 配置文件
config.yaml                       # 配置文件模板
config.sample.yaml               # 示例配置文件
.env.template                    # 环境变量模板

# 构建文件
pyproject.toml                   # 现代化项目配置
setup.py                         # 兼容性安装脚本
requirements.txt                 # 依赖列表
main.py                          # 主入口文件
```

## 🎯 最佳实践

### 生产环境部署建议

1. **使用环境变量**：避免敏感信息暴露在配置文件中
2. **启用日志轮转**：防止日志文件过大
3. **后台运行**：使用 `nohup` 或 `systemd` 管理进程
4. **监控内存使用**：在低内存服务器上调整性能参数
5. **定期备份**：备份迁移记录和配置文件

### 迁移策略建议

1. **先试运行**：使用 `--dry-run` 查看将要迁移的制品
2. **分批迁移**：大型项目可以分批次迁移
3. **验证结果**：迁移完成后验证 Nexus 中的制品
4. **保留记录**：首次迁移建议保留记录文件便于排查

## 📄 许可证

本项目采用 Apache 许可证，详见 LICENSE 文件。