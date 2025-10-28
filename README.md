# CODING Maven 制品库迁移工具

用于将 CODING 制品库中的 Maven 依赖迁移到 Nexus 仓库。

## 🚀 核心特性

- **零磁盘占用内存流水线** - 边下载边上传播，默认内存传输，不占用磁盘空间
- **智能去重机制** - 基于文件哈希避免重复上传，支持断点续传
- **高性能并发处理** - 针对 CODING 30 req/s 限制优化，多线程并发
- **自动版本识别** - 智能识别 SNAPSHOT 和 RELEASE 版本，自动分配到对应仓库
- **完善的错误处理** - 智能重试、速率限制处理、详细日志记录
- **灵活的配置选项** - 支持多仓库认证、包过滤、性能调优
- **🔥 Linux部署支持** - 支持外部配置文件和环境变量，适合服务器部署
- **🔧 增量迁移** - 支持断点续传，避免重复上传已迁移的制品
- **📊 详细日志** - 清晰显示上传进度和已上传的依赖列表

## 📦 使用要求

- Python 3.7+
- CODING 账户和 API Token
- Nexus 仓库访问权限

## 🚀 快速开始

### 方式一：开发环境快速开始

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

#### 2. 创建配置文件

```bash
python main.py init-config
```

这会创建一个 `config.sample.yaml` 文件，复制并重命名为 `config.yaml`：

```bash
cp config.sample.yaml config.yaml
```

#### 3. 配置信息

编辑 `config.yaml` 文件，填入您的实际配置：

### 方式二：Linux服务器部署

#### 1. 构建分发包

```bash
pip install build
python -m build
```

#### 2. 上传到服务器

将 `dist/coding-nexus-migrator-1.0.0-py3-none-any.whl` 上传到Linux服务器

#### 3. 服务器安装和配置

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装工具
pip install coding-nexus-migrator-1.0.0-py3-none-any.whl

# 配置方式1：使用配置文件
cp config-linux.yaml config.yaml
vi config.yaml

# 配置方式2：使用环境变量（推荐）
export CODING_TOKEN="your_token"
export CODING_TEAM_ID="your_team_id"
export NEXUS_URL="http://nexus:8081"
export NEXUS_USERNAME="user"
export NEXUS_PASSWORD="password"

# 配置方式3：混合模式（最灵活）
# 配置文件存放基本设置，环境变量覆盖敏感信息
cp .env.template .env
vi .env
source .env
```

#### 4. 运行迁移

```bash
# 验证配置
cnm verify-config --config config-linux.yaml

# 执行迁移
cnm migrate --projects your_project --config config-linux.yaml

# 后台运行
nohup cnm migrate --projects your_project --config config-linux.yaml > migration.log 2>&1 &
```

```yaml
# CODING 配置
coding:
  token: "your_coding_token_here"
  team_id: 123456

  # Maven 仓库认证配置
  maven_repositories:
    your-repo-name:
      username: "your_username"
      password: "your_password"

  # Maven 包过滤配置
  maven_filter:
    enabled: true
    patterns:
      - "com.yourcompany.*"

  # 性能优化配置
  performance:
    max_workers: 12  # 并发工作线程数
    batch_size: 50   # 批处理大小

  # 分页限制配置
  pagination:
    page_size: 100   # 每页获取的包数量
    max_pages: 50    # 最大页数限制

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
    - "project1"
    - "project2"
  download_path: "./target/downloads"
  batch_size: 500
  parallel_downloads: 10
```

### 4. 测试连接

```bash
# 开发环境
python main.py test-connections

# Linux服务器（安装后）
cnm verify-config
```

### 5. 查看 CODING 可用项目

```bash
# 开发环境
python main.py list-projects

# Linux服务器（安装后）
cnm list-projects --config config-linux.yaml
```

### 6. 查看 Nexus 仓库信息

```bash
# 开发环境
python main.py repository-info

# Linux服务器（安装后）
cnm repository-info --config config-linux.yaml
```

### 7. 执行迁移

```bash
# 开发环境 - 内存流水线模式（推荐）
python main.py migrate-memory-pipeline your_project

# Linux服务器 - 内存流水线模式（推荐）
cnm migrate --projects your_project --config config-linux.yaml

# Linux服务器 - 标准模式（适合调试）
cnm migrate --projects your_project --standard-mode --config config-linux.yaml

# 试运行（只查看不执行）
cnm migrate --projects your_project --dry-run --config config-linux.yaml
```

## 📋 命令行接口

### 全局选项

- `--config, -c`: 指定配置文件路径（默认：config.yaml）
- `--verbose, -v`: 详细输出模式

### 环境变量支持

支持以下环境变量覆盖配置文件：

- `CODING_TOKEN`: CODING API Token
- `CODING_TEAM_ID`: CODING 团队ID
- `NEXUS_URL`: Nexus服务器URL
- `NEXUS_USERNAME`: Nexus用户名
- `NEXUS_PASSWORD`: Nexus密码
- `NEXUS_REPOSITORY`: Nexus Release仓库名
- `NEXUS_SNAPSHOT_REPOSITORY`: Nexus Snapshot仓库名

### 主要命令

#### `migrate` - 执行迁移（推荐）

**默认内存流水线模式**：零磁盘占用、边下载边上传、完成后清理记录

```bash
# 使用配置文件中的项目列表
python main.py migrate

# 指定单个项目
python main.py migrate --projects myproject

# 指定多个项目
python main.py migrate --projects "myproject,other"

# 简短形式
python main.py migrate -p myproject
```

**选项**：
- `--projects, -p`: 指定要迁移的项目，多个项目用逗号分隔
- `--cleanup`: 迁移完成后清理下载文件（仅标准模式）
- `--dry-run`: 试运行，只查看要迁移的制品，不执行下载
- `--standard-mode`: 使用标准模式（下载到本地再上传）
- `--keep-records`: 保留迁移记录文件，默认完成后清理
- `--filter, -f`: 包过滤规则，多个规则用逗号分隔，覆盖配置文件设置

#### `migrate-all` - 迁移所有配置的项目

```bash
python main.py migrate-all [--cleanup]
```

#### `migrate-pipeline` - 流水线迁移（边下载边上传）

```bash
python main.py migrate-pipeline PROJECT_NAME
```

#### `migrate-memory-pipeline` - 显式内存流水线迁移

```bash
python main.py migrate-memory-pipeline PROJECT_NAME [--cleanup]
```

#### `list-projects` - 列出 CODING 可用项目

```bash
python main.py list-projects
```

#### `repository-info` - 显示 Nexus 仓库信息

```bash
python main.py repository-info
```

#### `init-config` - 创建示例配置文件

```bash
python main.py init-config [--output OUTPUT_FILE]
```

## 🚀 Linux服务器部署

### 1. 安装打包工具

```bash
pip install build
```

### 2. 构建分发包

```bash
python -m build
```

这会在 `dist/` 目录下生成：
- `coding-nexus-migrator-1.0.0-py3-none-any.whl` (wheel包)
- `coding-nexus-migrator-1.0.0.tar.gz` (源码包)

### 3. 上传到Linux服务器

将生成的包文件上传到目标Linux服务器

### 4. 在Linux服务器上安装

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖包
pip install --upgrade pip

# 安装迁移工具
pip install coding-nexus-migrator-1.0.0-py3-none-any.whl

# 或者从源码安装
# pip install coding-nexus-migrator-1.0.0.tar.gz
```

### 5. 配置文件和环境变量

#### 🔧 配置方式对比

| 配置方式 | 适用场景 | 优点 | 缺点 |
|---------|---------|------|------|
| **配置文件** | 开发测试、简单部署 | 配置集中、易于管理 | 敏感信息暴露 |
| **环境变量** | CI/CD、生产环境 | 安全、灵活 | 需要设置多个变量 |
| **混合模式** | 复杂部署环境 | 安全又灵活 | 配置稍复杂 |

#### 方法一：使用配置文件（推荐开发环境）

```bash
# 复制Linux配置模板
cp config-linux.yaml config.yaml

# 编辑配置文件
vi config.yaml  # 或使用其他编辑器
```

#### 方法二：使用环境变量（推荐生产环境）

```bash
# 设置环境变量
export CODING_TOKEN="your_coding_token"
export CODING_TEAM_ID="your_team_id"
export NEXUS_URL="http://your-nexus:8081"
export NEXUS_USERNAME="your_username"
export NEXUS_PASSWORD="your_password"
export NEXUS_REPOSITORY="maven-releases"
export NEXUS_SNAPSHOT_REPOSITORY="maven-snapshots"
```

#### 方法三：混合模式（最灵活）

配置文件中存放基本配置，敏感信息通过环境变量覆盖：

```bash
# 使用 .env 文件管理环境变量
cp .env.template .env
vi .env

# 加载环境变量
source .env

# 验证配置
cnm verify-config --config config-linux.yaml
```

#### 📁 配置文件说明

- `config-linux.yaml`: Linux服务器专用配置模板
- `.env.template`: 环境变量模板
- `config.yaml`: 实际使用的配置文件（需要创建）

### 6. 运行迁移

```bash
# 检查环境
cnm list-projects --config config-linux.yaml

# 验证配置
cnm verify-config --config config-linux.yaml

# 执行迁移（内存流水线模式，低内存占用）
cnm migrate --projects your_project_name --config config-linux.yaml

# 使用标准模式（适合调试）
cnm migrate --projects your_project_name --standard-mode --config config-linux.yaml

# 后台运行
nohup cnm migrate --projects your_project_name --config config-linux.yaml > migration.log 2>&1 &
```

### 7. 常用命令

```bash
# 创建示例配置文件
cnm init-config --output my-config.yaml

# 列出所有项目
cnm list-projects

# 查看Nexus仓库信息
cnm repository-info

# 验证配置和环境变量
cnm verify-config

# 试运行（只查看不执行）
cnm migrate --projects your_project --dry-run

# 指定多个项目
cnm migrate --projects "project1,project2,project3"

# 使用包过滤
cnm migrate --projects your_project --filter "com.company.*,com.org.*"
```

### 低内存服务器优化

对于内存受限的服务器（< 2GB），建议：

```bash
# 设置环境变量优化内存使用
export PYTHONOPTIMIZE=1
export PYTHONDONTWRITEBYTECODE=1

# 使用更小的批处理
cnm migrate --projects your_project_name --config low-memory-config.yaml
```

创建 `low-memory-config.yaml`：

```yaml
# 低内存优化配置
performance:
  max_workers: 1
  memory_limit_mb: 256
  batch_size: 10

pagination:
  page_size: 10

rate_limit:
  requests_per_second: 3
```

## 🔧 迁移模式说明

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

## 📊 使用示例

### 示例 1：完整迁移流程

```bash
# 1. 创建配置文件
python main.py init-config

# 2. 编辑配置文件
# 编辑 config.yaml，填入您的配置信息

# 3. 测试连接
python main.py test-connections

# 4. 查看 CODING 可用项目
python main.py list-projects

# 5. 查看 Nexus 仓库信息
python main.py repository-info

# 6. 执行迁移（默认内存流水线模式）
python main.py migrate --projects myproject
```

### 示例 2：查看仓库映射

```bash
python main.py repository-info

# 输出示例：
# Nexus 仓库信息:
#   - maven-releases: maven2 (hosted)
#   - maven-snapshots: maven2 (hosted)
#   - maven-central: maven2 (proxy)
#   - maven-public: maven2 (group)
# 检测到的仓库:
#   SNAPSHOT 仓库: maven-snapshots
#   RELEASE 仓库: maven-releases
```

### 示例 3：不同迁移模式

```bash
# 内存流水线模式（推荐）
python main.py migrate --projects myproject

# 标准模式
python main.py migrate --projects myproject --standard-mode

# 试运行模式
python main.py migrate --projects myproject --dry-run

# 保留迁移记录
python main.py migrate --projects myproject --keep-records

# 使用包过滤规则（覆盖配置文件设置）
python main.py migrate --projects myproject --filter "com.yourcompany.*"
python main.py migrate --projects myproject --filter "com.yourcompany.*,org.yourorg.*"
```

## 🎯 SNAPSHOT 和 RELEASE 版本处理

工具会自动识别 Maven 制品的版本类型并分配到相应的 Nexus 仓库：

### 版本识别规则

- **SNAPSHOT 版本**：版本号以 `-SNAPSHOT` 结尾（不区分大小写）
  - 例如：`1.0.0-SNAPSHOT`、`2.1.0-snapshot`、`3.0-SNAPSHOT`

- **RELEASE 版本**：所有非 SNAPSHOT 版本
  - 例如：`1.0.0`、`2.1.0`、`3.0.0.RELEASE`

### 仓库检测机制

1. **配置文件指定**：优先使用配置文件中的 `release_repo` 和 `snapshot_repo`
2. **自动检测**：自动检测 Nexus 中的 Maven 仓库
3. **默认仓库**：如果检测失败，使用配置的默认仓库

## ⚡ 性能优化

### CODING API 限制处理

- **智能速率限制**：自动检测 CODING 的 30 req/s 限制
- **并发控制**：默认 12 个并发工作线程
- **自动重试**：遇到限流时智能等待重试

### 内存管理

- **内存使用限制**：默认最大 100MB 内存使用
- **流式处理**：边下载边上传，不积累文件在内存中
- **即时清理**：上传成功后立即释放内存

### 并发优化

```yaml
coding:
  performance:
    max_workers: 12  # 建议设置为 CODING 限制的 25 req/s 以下
    batch_size: 50   # 批处理大小
```

## 🛠️ 配置说明

### CODING 配置

```yaml
coding:
  token: "your_coding_token"
  team_id: 123456

  # Maven 仓库认证（多仓库支持）
  maven_repositories:
    repo-releases:
      username: "releases-user"
      password: "releases-pass"
    repo-snapshots:
      username: "snapshots-user"
      password: "snapshots-pass"

  # 包过滤规则
  maven_filter:
    enabled: true
    patterns:
      - "com.yourcompany.*"
      - "org.yourorg.*"

  # 性能调优
  performance:
    max_workers: 12
    batch_size: 50

  # 分页控制
  pagination:
    page_size: 100
    max_pages: 50
```

### Nexus 配置

```yaml
nexus:
  url: "http://localhost:8081"
  username: "admin"
  password: "admin123"
  release_repo: "maven-releases"
  snapshot_repo: "maven-snapshots"
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

程序运行时会生成日志文件 `target/migration.log`，包含详细的运行信息和错误信息。

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
config-linux.yaml                 # Linux服务器配置模板
.env.template                     # 环境变量模板
config.sample.yaml                # 示例配置文件

# 构建文件
pyproject.toml                    # 现代化项目配置
setup.py                          # 兼容性安装脚本
requirements.txt                  # 依赖列表
```

## 🎯 部署总结

### 本地开发
```bash
# 安装依赖
pip install -r requirements.txt

# 创建配置
python main.py init-config

# 运行迁移
python main.py migrate-memory-pipeline your_project
```

### Linux服务器部署
```bash
# 1. 构建分发包
python -m build

# 2. 服务器安装
pip install coding-nexus-migrator-1.0.0-py3-none-any.whl

# 3. 配置（三选一）
# 方法1：配置文件
cp config-linux.yaml config.yaml && vi config.yaml

# 方法2：环境变量
export CODING_TOKEN="xxx" && export NEXUS_URL="xxx" ...

# 方法3：混合模式
cp .env.template .env && vi .env && source .env

# 4. 运行迁移
cnm migrate --projects your_project --config config-linux.yaml
```

### 关键特性
- ✅ **零磁盘占用** - 内存流水线模式
- ✅ **增量迁移** - 支持断点续传
- ✅ **环境变量支持** - 灵活的配置方式
- ✅ **详细日志** - 清晰的进度显示
- ✅ **Linux优化** - 针对服务器环境优化

## 📄 许可证

本项目采用 MIT 许可证。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！