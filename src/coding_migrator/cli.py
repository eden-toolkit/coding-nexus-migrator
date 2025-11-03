#!/usr/bin/env python3
"""
命令行接口模块
支持外部配置文件和环境变量
"""

import os
import sys
import click
import logging
import psutil
import signal
from pathlib import Path
from typing import Optional, List

from .config import ConfigManager
from .migrator import MavenMigrator
from .memory_pipeline_migrator import MemoryPipelineMigrator


def setup_logging(verbose: bool = False, log_file: str = None, max_size_mb: int = 10, backup_count: int = 5):
    """设置日志配置"""
    level = logging.DEBUG if verbose else logging.INFO

    # 清除现有的处理器
    logger = logging.getLogger()
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 设置根logger
    logger.setLevel(level)

    # 创建格式化器
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器（带轮转）
    if log_file:
        from logging.handlers import RotatingFileHandler

        # 确保日志目录存在
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            filename=log_path,
            maxBytes=max_size_mb * 1024 * 1024,  # 转换为字节
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        logger.info(f"日志文件: {log_path} (最大 {max_size_mb}MB, 保留 {backup_count} 个备份)")

    return logger


def load_logging_config(config_file: str):
    """从配置文件加载日志配置"""
    try:
        import yaml
        config_path = Path(config_file)
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            # 从配置文件中读取日志配置
            logging_config = config_data.get('logging', {})
            return {
                'log_file': logging_config.get('file', 'target/migration.log'),
                'max_size_mb': logging_config.get('max_size_mb', 10),
                'backup_count': logging_config.get('backup_count', 5),
                'level': logging_config.get('level', 'INFO')
            }
    except Exception as e:
        # 如果读取失败，使用默认配置
        logger = logging.getLogger(__name__)
        logger.warning(f"无法读取日志配置，使用默认设置: {e}")
        return {
            'log_file': 'target/migration.log',
            'max_size_mb': 10,
            'backup_count': 5,
            'level': 'INFO'
        }


@click.group()
@click.option('--config', '-c', default='config.yaml',
              help='配置文件路径 (默认: config.yaml)')
@click.option('--verbose', '-v', is_flag=True,
              help='详细输出模式')
@click.pass_context
def cli(ctx, config, verbose):
    """CODING Maven 制品库迁移工具

    支持环境变量配置：
    - CODING_TOKEN: CODING API Token
    - CODING_TEAM_ID: CODING 团队ID
    - NEXUS_URL: Nexus服务器URL
    - NEXUS_USERNAME: Nexus用户名
    - NEXUS_PASSWORD: Nexus密码

    默认使用内存流水线模式：零磁盘占用、边下载边上传、完成后清理记录
    """
    ctx.ensure_object(dict)
    ctx.obj['config_file'] = config
    ctx.obj['verbose'] = verbose

    # 加载日志配置
    logging_config = load_logging_config(config)
    ctx.obj['logging_config'] = logging_config

    # 设置日志级别
    log_level = logging_config.get('level', 'INFO')
    verbose = verbose or (log_level.upper() == 'DEBUG')

    setup_logging(
        verbose=verbose,
        log_file=logging_config['log_file'],
        max_size_mb=logging_config['max_size_mb'],
        backup_count=logging_config['backup_count']
    )


@cli.command()
@click.option('--output', '-o', default='config.sample.yaml',
              help='输出配置文件路径')
def init_config(output):
    """创建示例配置文件"""
    try:
        config_manager = ConfigManager()
        config_manager.create_sample_config(output)
        click.echo(f"[OK] 示例配置文件已创建: {output}")
        click.echo("请编辑配置文件，填入您的实际配置信息。")
        click.echo("\n💡 提示：也可以使用环境变量替代配置文件中的敏感信息")
    except Exception as e:
        click.echo(f"[ERROR] 创建配置文件失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def list_projects(ctx):
    """列出所有可用的项目"""
    try:
        config_manager = ConfigManager(ctx.obj['config_file'])
        config = config_manager.load_config_with_env()

        migrator = MavenMigrator(config)
        projects = migrator.get_projects()

        click.echo("📋 可用的项目列表:")
        click.echo("=" * 60)

        for project in projects:
            click.echo(f"ID: {project.id}")
            click.echo(f"名称: {project.name}")
            click.echo(f"显示: {project.display_name}")
            click.echo(f"描述: {project.description}")
            click.echo("-" * 40)

    except Exception as e:
        click.echo(f"[ERROR] 获取项目列表失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--projects', '-p', help='要迁移的项目名称，多个项目用逗号分隔')
@click.option('--standard-mode', is_flag=True,
              help='使用标准模式（下载到本地再上传），默认使用内存流水线模式')
@click.option('--cleanup', is_flag=True,
              help='迁移完成后清理下载文件（仅标准模式）')
@click.option('--dry-run', is_flag=True,
              help='试运行，只查看要迁移的制品，不执行下载')
@click.option('--keep-records', is_flag=True,
              help='保留迁移记录文件，默认完成后清理')
@click.option('--filter', '-f', help='包过滤规则，多个规则用逗号分隔，覆盖配置文件设置')
@click.pass_context
def migrate(ctx, projects, standard_mode, cleanup, dry_run, keep_records, filter):
    """执行Maven制品迁移（推荐使用内存流水线模式）"""
    try:
        config_manager = ConfigManager(ctx.obj['config_file'])
        config = config_manager.load_config_with_env()

        # 应用命令行过滤规则
        if filter:
            filter_patterns = [p.strip() for p in filter.split(',')]
            config.maven_filter.patterns = filter_patterns

        if dry_run:
            click.echo("[SEARCH] 试运行模式 - 只查看要迁移的制品")

        if standard_mode:
            click.echo("📁 使用标准模式（下载到本地）")
            migrator = MavenMigrator(config)

            if projects:
                project_names = [p.strip() for p in projects.split(',')]
                for project_name in project_names:
                    click.echo(f"\n[START] 开始迁移项目: {project_name}")
                    result = migrator.migrate_project_cli(
                        project_name,
                        cleanup=cleanup,
                        dry_run=dry_run
                    )
                    _display_result(result)
            else:
                click.echo("[START] 开始迁移所有配置的项目")
                result = migrator.migrate_all(
                    cleanup=cleanup,
                    dry_run=dry_run
                )
                _display_result(result)
        else:
            click.echo("⚡ 使用内存流水线模式（零磁盘占用）")
            migrator = MemoryPipelineMigrator(config)

            # 确定要迁移的项目列表
            # 优先级：命令行参数 > 配置文件 > 所有项目
            target_project_names = None

            if projects:
                # 1. 使用命令行指定的项目
                target_project_names = [p.strip() for p in projects.split(',')]
                click.echo(f"📋 使用命令行指定的项目: {', '.join(target_project_names)}")
            elif config.project_names:
                # 2. 使用配置文件中的项目列表
                target_project_names = config.project_names
                click.echo(f"📋 使用配置文件中的项目: {', '.join(target_project_names)}")
            else:
                # 3. 迁移所有项目
                click.echo("[SEARCH] 未指定项目，将迁移所有项目")

            # 获取完整的项目列表用于查找
            projects_list = migrator.coding_client.get_all_projects()
            if not projects_list:
                click.echo("[ERROR] 未找到任何项目")
                sys.exit(1)

            # 如果指定了项目名称，过滤项目列表
            if target_project_names:
                click.echo(f"📋 找到 {len(projects_list)} 个项目，将迁移以下指定项目:")
                matched_projects = []

                for project_name in target_project_names:
                    found = False
                    for project in projects_list:
                        if project.name == project_name:
                            matched_projects.append(project)
                            click.echo(f"  - {project.name} (ID: {project.id})")
                            found = True
                            break

                    if not found:
                        click.echo(f"  ⚠️  未找到项目: {project_name}")

                if not matched_projects:
                    click.echo("[ERROR] 没有找到任何匹配的项目")
                    sys.exit(1)

                # 只迁移匹配的项目
                for project in matched_projects:
                    click.echo(f"\n[START] 开始内存迁移项目: {project.name}")
                    result = migrator.migrate_project(project.id, project.name)
                    _display_result(result)
            else:
                # 迁移所有项目
                click.echo(f"📋 找到 {len(projects_list)} 个项目，将依次迁移:")
                for project in projects_list:
                    click.echo(f"  - {project.name} (ID: {project.id})")

                for project in projects_list:
                    click.echo(f"\n[START] 开始内存迁移项目: {project.name}")
                    result = migrator.migrate_project(project.id, project.name)
                    _display_result(result)

    except Exception as e:
        click.echo(f"[ERROR] 迁移失败: {e}", err=True)
        if ctx.obj['verbose']:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option('--cleanup', is_flag=True, help='迁移完成后清理下载文件')
@click.pass_context
def migrate_all(ctx, cleanup):
    """迁移所有配置的项目"""
    try:
        config_manager = ConfigManager(ctx.obj['config_file'])
        config = config_manager.load_config_with_env()

        migrator = MavenMigrator(config)
        result = migrator.migrate_all(cleanup=cleanup)
        _display_result(result)

    except Exception as e:
        click.echo(f"[ERROR] 迁移失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('project_name')
@click.option('--cleanup', is_flag=True, help='迁移完成后清理下载文件')
@click.pass_context
def migrate_memory_pipeline(ctx, project_name, cleanup):
    """使用内存流水线模式迁移指定项目（零磁盘占用）"""
    try:
        config_manager = ConfigManager(ctx.obj['config_file'])
        config = config_manager.load_config_with_env()

        migrator = MemoryPipelineMigrator(config)
        result = migrator.migrate_project(project_name, project_name)
        _display_result(result)

    except Exception as e:
        click.echo(f"[ERROR] 内存迁移失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def repository_info(ctx):
    """显示Nexus仓库信息"""
    try:
        config_manager = ConfigManager(ctx.obj['config_file'])
        config = config_manager.load_config_with_env()

        migrator = MavenMigrator(config)
        repositories = migrator.get_repository_info()

        click.echo("[INFO] Nexus仓库信息:")
        click.echo("=" * 60)

        if isinstance(repositories, dict):
            # 检查是否是多个仓库的信息（新格式）
            if 'name' not in repositories:
                # 多个仓库的情况
                click.echo(f"找到 {len(repositories)} 个 Maven 仓库:")
                click.echo()
                for repo_name, repo_data in repositories.items():
                    click.echo(f"仓库名称: {repo_data.get('name', 'Unknown')}")
                    click.echo(f"仓库格式: {repo_data.get('format', 'Unknown')}")
                    click.echo(f"仓库类型: {repo_data.get('type', 'Unknown')}")
                    click.echo(f"仓库URL: {repo_data.get('url', 'Unknown')}")
                    click.echo(f"仓库大小: {repo_data.get('size', 0)} bytes")
                    click.echo(f"制品数量: {repo_data.get('count', 0)}")
                    click.echo("-" * 40)
            else:
                # 单个仓库的情况（向后兼容）
                click.echo(f"仓库名称: {repositories.get('name', 'Unknown')}")
                click.echo(f"仓库格式: {repositories.get('format', 'Unknown')}")
                click.echo(f"仓库类型: {repositories.get('type', 'Unknown')}")
                click.echo(f"仓库URL: {repositories.get('url', 'Unknown')}")
                click.echo(f"仓库大小: {repositories.get('size', 0)} bytes")
        elif isinstance(repositories, list):
            # 列表格式（旧格式兼容）
            for repo in repositories:
                click.echo(f"名称: {repo.get('name', 'N/A')}")
                click.echo(f"格式: {repo.get('format', 'N/A')}")
                click.echo(f"类型: {repo.get('type', 'N/A')}")
                click.echo(f"URL: {repo.get('url', 'N/A')}")
                click.echo("-" * 40)
        else:
            click.echo(f"仓库信息: {repositories}")

    except Exception as e:
        click.echo(f"[ERROR] 获取仓库信息失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--force', '-f', is_flag=True, help='强制终止进程，不询问确认')
@click.option('--all', '-a', is_flag=True, help='终止所有找到的迁移进程')
@click.pass_context
def stop(ctx, force, all):
    """停止正在运行的迁移进程"""
    try:
        click.echo("🔍 正在查找正在运行的迁移进程...")

        # 查找迁移进程
        migration_processes = _find_migration_processes()

        if not migration_processes:
            click.echo("[INFO] 未找到正在运行的迁移进程")
            return

        click.echo(f"[FOUND] 找到 {len(migration_processes)} 个正在运行的迁移进程:")
        click.echo("=" * 80)

        for i, proc in enumerate(migration_processes, 1):
            click.echo(f"{i}. PID: {proc['pid']}")
            click.echo(f"   命令: {proc['cmdline']}")
            click.echo(f"   启动时间: {proc['create_time']}")
            click.echo(f"   运行时间: {proc['running_time']}")
            click.echo(f"   内存使用: {proc['memory_info']}")
            click.echo("-" * 40)

        # 确定要终止的进程
        processes_to_kill = migration_processes if all else [migration_processes[0]]

        if not force:
            if all:
                click.echo(f"\n⚠️  确认要终止所有 {len(processes_to_kill)} 个迁移进程吗? [y/N]")
            else:
                click.echo(f"\n⚠️  确认要终止进程 PID {processes_to_kill[0]['pid']} 吗? [y/N]")

            response = input().strip().lower()
            if response not in ['y', 'yes']:
                click.echo("[CANCEL] 操作已取消")
                return

        # 终止进程
        success_count = 0
        failed_count = 0

        for proc in processes_to_kill:
            try:
                # 尝试优雅地终止进程
                process = psutil.Process(proc['pid'])
                click.echo(f"[STOPPING] 正在终止进程 PID {proc['pid']}...")

                # 发送 SIGTERM 信号
                process.terminate()

                # 等待进程结束
                try:
                    process.wait(timeout=10)
                    click.echo(f"[OK] 进程 PID {proc['pid']} 已优雅终止")
                    success_count += 1
                except psutil.TimeoutExpired:
                    # 如果优雅终止失败，强制终止
                    if force:
                        click.echo(f"[FORCE] 强制终止进程 PID {proc['pid']}...")
                        process.kill()
                        process.wait(timeout=5)
                        click.echo(f"[OK] 进程 PID {proc['pid']} 已强制终止")
                        success_count += 1
                    else:
                        click.echo(f"[FAILED] 进程 PID {proc['pid']} 终止超时，使用 --force 强制终止")
                        failed_count += 1

            except psutil.NoSuchProcess:
                click.echo(f"[INFO] 进程 PID {proc['pid']} 已不存在")
                success_count += 1
            except Exception as e:
                click.echo(f"[ERROR] 终止进程 PID {proc['pid']} 失败: {e}")
                failed_count += 1

        click.echo(f"\n📊 操作完成: {success_count} 个进程已终止, {failed_count} 个失败")

        if failed_count > 0:
            click.echo("💡 提示: 如果进程无法终止，可以尝试使用 --force 参数")

    except Exception as e:
        click.echo(f"[ERROR] 停止进程失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def status(ctx):
    """显示迁移进程状态"""
    try:
        click.echo("🔍 正在查找迁移进程...")

        # 查找迁移进程
        migration_processes = _find_migration_processes()

        if not migration_processes:
            click.echo("[INFO] 未找到正在运行的迁移进程")
            return

        click.echo(f"[FOUND] 找到 {len(migration_processes)} 个正在运行的迁移进程:")
        click.echo("=" * 100)

        total_memory = 0
        for i, proc in enumerate(migration_processes, 1):
            click.echo(f"📋 进程 #{i}")
            click.echo(f"   PID: {proc['pid']}")
            click.echo(f"   命令: {proc['cmdline']}")
            click.echo(f"   启动时间: {proc['create_time']}")
            click.echo(f"   运行时间: {proc['running_time']}")
            click.echo(f"   CPU使用率: {proc['cpu_percent']:.1f}%")
            click.echo(f"   内存使用: {proc['memory_info']}")
            click.echo(f"   状态: {proc['status']}")
            click.echo(f"   工作目录: {proc['cwd']}")

            # 累计内存使用
            memory_mb = proc['memory_mb']
            total_memory += memory_mb

            click.echo("-" * 50)

        click.echo(f"📊 总计:")
        click.echo(f"   进程数量: {len(migration_processes)}")
        click.echo(f"   总内存使用: {total_memory:.1f} MB")
        click.echo(f"   平均内存: {total_memory/len(migration_processes):.1f} MB")

        # 提供操作建议
        click.echo(f"\n💡 可用操作:")
        click.echo(f"   cnm stop              # 停止第一个进程")
        click.echo(f"   cnm stop --all        # 停止所有进程")
        click.echo(f"   cnm stop --force      # 强制停止进程")

    except Exception as e:
        click.echo(f"[ERROR] 获取进程状态失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def verify_config(ctx):
    """验证配置文件和环境变量"""
    try:
        config_file = ctx.obj['config_file']
        click.echo(f"[SEARCH] 验证配置文件: {config_file}")

        # 检查配置文件是否存在
        if not Path(config_file).exists():
            click.echo(f"[ERROR] 配置文件不存在: {config_file}")
            sys.exit(1)

        # 尝试加载配置
        config_manager = ConfigManager(config_file)
        config = config_manager.load_config_with_env()

        click.echo("[OK] 配置文件格式正确")

        # 检查环境变量
        env_vars = {
            'CODING_TOKEN': os.getenv('CODING_TOKEN'),
            'CODING_TEAM_ID': os.getenv('CODING_TEAM_ID'),
            'NEXUS_URL': os.getenv('NEXUS_URL'),
            'NEXUS_USERNAME': os.getenv('NEXUS_USERNAME'),
            'NEXUS_PASSWORD': os.getenv('NEXUS_PASSWORD'),
        }

        click.echo("\n🌍 环境变量状态:")
        for var, value in env_vars.items():
            if value:
                if var in ['CODING_TOKEN', 'NEXUS_PASSWORD']:
                    click.echo(f"[OK] {var}: ***已设置***")
                else:
                    click.echo(f"[OK] {var}: {value}")
            else:
                click.echo(f"⚠️  {var}: 未设置（将从配置文件读取）")

        click.echo("\n🎯 配置验证完成！")

    except Exception as e:
        click.echo(f"[ERROR] 配置验证失败: {e}", err=True)
        sys.exit(1)


def _find_migration_processes() -> List[dict]:
    """查找正在运行的迁移进程"""
    migration_processes = []

    try:
        # 获取所有进程
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'cwd', 'status']):
            try:
                # 获取进程信息
                cmdline = proc.info.get('cmdline', [])
                if not cmdline:
                    continue

                # 检查是否是迁移进程
                cmdline_str = ' '.join(cmdline)
                is_migration_process = (
                    'coding_migrator' in cmdline_str or
                    'memory_pipeline_migrator' in cmdline_str or
                    ('python' in cmdline_str and 'migrate' in cmdline_str) or
                    ('cnm' in cmdline_str and ('migrate' in cmdline_str or 'memory' in cmdline_str))
                )

                if is_migration_process:
                    # 获取详细的进程信息
                    try:
                        memory_info = proc.memory_info()
                        memory_mb = memory_info.rss / 1024 / 1024  # 转换为MB
                        cpu_percent = proc.cpu_percent()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        memory_info = "N/A"
                        memory_mb = 0
                        cpu_percent = 0

                    # 格式化启动时间和运行时间
                    import datetime
                    create_time = datetime.datetime.fromtimestamp(proc.info['create_time'])
                    running_time = datetime.datetime.now() - create_time

                    # 格式化运行时间
                    days = running_time.days
                    hours, remainder = divmod(running_time.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    running_time_str = ""
                    if days > 0:
                        running_time_str += f"{days}天 "
                    if hours > 0:
                        running_time_str += f"{hours}小时 "
                    if minutes > 0:
                        running_time_str += f"{minutes}分钟 "
                    running_time_str += f"{seconds}秒"

                    # 格式化内存信息
                    if isinstance(memory_info, tuple) and len(memory_info) >= 1:
                        memory_str = f"{memory_mb:.1f} MB"
                    else:
                        memory_str = "N/A"

                    migration_processes.append({
                        'pid': proc.info['pid'],
                        'cmdline': ' '.join(cmdline),
                        'create_time': create_time.strftime("%Y-%m-%d %H:%M:%S"),
                        'running_time': running_time_str,
                        'memory_info': memory_str,
                        'memory_mb': memory_mb,
                        'cpu_percent': cpu_percent,
                        'status': proc.info['status'],
                        'cwd': proc.info.get('cwd', 'N/A')
                    })

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    except Exception as e:
        click.echo(f"[WARNING] 查找进程时出现错误: {e}")

    # 按启动时间排序（最早的在前）
    migration_processes.sort(key=lambda x: x['create_time'])

    return migration_processes


def _display_result(result):
    """显示迁移结果"""
    click.echo("\n" + "=" * 60)
    click.echo("📊 迁移结果汇总")
    click.echo("=" * 60)

    if isinstance(result, dict):
        for key, value in result.items():
            if key == 'total_artifacts':
                click.echo(f"总制品数: {value}")
            elif key == 'downloaded':
                click.echo(f"已下载: {value}")
            elif key == 'uploaded':
                click.echo(f"已上传: {value}")
            elif key == 'skipped_existing':
                click.echo(f"跳过已存在: {value}")
            elif key == 'download_failed':
                click.echo(f"下载失败: {value}")
            elif key == 'upload_failed':
                click.echo(f"上传失败: {value}")
            else:
                click.echo(f"{key}: {value}")

    click.echo("=" * 60)


def main():
    """主入口点"""
    cli()


if __name__ == '__main__':
    main()