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


def setup_logging(verbose: bool = False):
    """设置日志配置"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


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

    setup_logging(verbose)


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
            config.maven_filter.package_patterns = filter_patterns

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
                    result = migrator.migrate_project(project_name, project_name)
                    _display_result(result)
            else:
                click.echo("❌ 内存流水线模式需要指定项目名称")
                click.echo("使用 --projects 参数指定项目，或使用标准模式")
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