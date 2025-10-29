#!/usr/bin/env python3
"""
命令行接口模块
支持外部配置文件和环境变量
"""

import os
import sys
import click
import logging
from pathlib import Path
from typing import Optional

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
        click.echo(f"✅ 示例配置文件已创建: {output}")
        click.echo("请编辑配置文件，填入您的实际配置信息。")
        click.echo("\n💡 提示：也可以使用环境变量替代配置文件中的敏感信息")
    except Exception as e:
        click.echo(f"❌ 创建配置文件失败: {e}", err=True)
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
            click.echo(f"显示名: {project.display_name}")
            click.echo(f"描述: {project.description}")
            click.echo("-" * 40)

    except Exception as e:
        click.echo(f"❌ 获取项目列表失败: {e}", err=True)
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
            click.echo("🔍 试运行模式 - 只查看要迁移的制品")

        if standard_mode:
            click.echo("📁 使用标准模式（下载到本地）")
            migrator = MavenMigrator(config)

            if projects:
                project_names = [p.strip() for p in projects.split(',')]
                for project_name in project_names:
                    click.echo(f"\n🚀 开始迁移项目: {project_name}")
                    result = migrator.migrate_project(
                        project_name,
                        cleanup=cleanup,
                        dry_run=dry_run
                    )
                    _display_result(result)
            else:
                click.echo("🚀 开始迁移所有配置的项目")
                result = migrator.migrate_all(
                    cleanup=cleanup,
                    dry_run=dry_run
                )
                _display_result(result)
        else:
            click.echo("⚡ 使用内存流水线模式（零磁盘占用）")
            migrator = MemoryPipelineMigrator(config)

            if projects:
                project_names = [p.strip() for p in projects.split(',')]
                for project_name in project_names:
                    click.echo(f"\n🚀 开始内存迁移项目: {project_name}")

                    # 获取项目ID
                    try:
                        projects_list = migrator.coding_client.get_projects()
                        target_project = None
                        for project in projects_list:
                            if project.name == project_name:
                                target_project = project
                                break

                        if not target_project:
                            click.echo(f"❌ 未找到项目: {project_name}")
                            continue

                        result = migrator.migrate_project(target_project.id, project_name)
                        _display_result(result)

                    except Exception as e:
                        click.echo(f"❌ 获取项目信息失败: {e}")
                        continue
            else:
                # 自动获取所有项目
                click.echo("🔍 未指定项目，自动获取所有项目进行迁移")
                try:
                    projects_list = migrator.coding_client.get_projects()
                    if not projects_list:
                        click.echo("❌ 未找到任何项目")
                        sys.exit(1)

                    click.echo(f"📋 找到 {len(projects_list)} 个项目，将依次迁移:")
                    for project in projects_list:
                        click.echo(f"  - {project.name} (ID: {project.id})")

                    for project in projects_list:
                        click.echo(f"\n🚀 开始内存迁移项目: {project.name}")
                        result = migrator.migrate_project(project.id, project.name)
                        _display_result(result)

                except Exception as e:
                    click.echo(f"❌ 获取项目列表失败: {e}")
                    sys.exit(1)

    except Exception as e:
        click.echo(f"❌ 迁移失败: {e}", err=True)
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
        click.echo(f"❌ 迁移失败: {e}", err=True)
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
        click.echo(f"❌ 内存迁移失败: {e}", err=True)
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

        click.echo("📦 Nexus仓库信息:")
        click.echo("=" * 60)

        for repo in repositories:
            click.echo(f"名称: {repo.get('name', 'N/A')}")
            click.echo(f"格式: {repo.get('format', 'N/A')}")
            click.echo(f"类型: {repo.get('type', 'N/A')}")
            click.echo(f"URL: {repo.get('url', 'N/A')}")
            click.echo("-" * 40)

    except Exception as e:
        click.echo(f"❌ 获取仓库信息失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def verify_config(ctx):
    """验证配置文件和环境变量"""
    try:
        config_file = ctx.obj['config_file']
        click.echo(f"🔍 验证配置文件: {config_file}")

        # 检查配置文件是否存在
        if not Path(config_file).exists():
            click.echo(f"❌ 配置文件不存在: {config_file}")
            sys.exit(1)

        # 尝试加载配置
        config_manager = ConfigManager(config_file)
        config = config_manager.load_config_with_env()

        click.echo("✅ 配置文件格式正确")

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
                    click.echo(f"✅ {var}: ***已设置***")
                else:
                    click.echo(f"✅ {var}: {value}")
            else:
                click.echo(f"⚠️  {var}: 未设置（将从配置文件读取）")

        click.echo("\n🎯 配置验证完成！")

    except Exception as e:
        click.echo(f"❌ 配置验证失败: {e}", err=True)
        sys.exit(1)


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