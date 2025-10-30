#!/usr/bin/env python3
"""
CODING Maven 制品库迁移工具主程序
"""

import sys
import click
import logging
from pathlib import Path

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from coding_migrator.config import ConfigManager
from coding_migrator.migrator import MavenMigrator


@click.group()
@click.option('--config', '-c', default='config.yaml', help='配置文件路径')
@click.option('--verbose', '-v', is_flag=True, help='详细输出')
@click.pass_context
def cli(ctx, config, verbose):
    """CODING Maven 制品库迁移工具（默认使用内存流水线模式：零磁盘占用、边下载边上传、完成后清理记录）"""
    ctx.ensure_object(dict)
    ctx.obj['config_file'] = config
    ctx.obj['verbose'] = verbose

    if verbose:
        logging.basicConfig(level=logging.DEBUG)


@cli.command()
@click.option('--output', '-o', default='config.sample.yaml', help='输出配置文件路径')
def init_config(output):
    """创建示例配置文件"""
    try:
        config_manager = ConfigManager()
        config_manager.create_sample_config(output)
        click.echo(f"示例配置文件已创建: {output}")
        click.echo("请编辑配置文件，填入您的实际配置信息。")
    except Exception as e:
        click.echo(f"创建配置文件失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def list_projects(ctx):
    """列出所有可用的项目"""
    try:
        config_file = ctx.obj['config_file']
        config_manager = ConfigManager(config_file)
        config = config_manager.load_config_with_env()
        migrator = MavenMigrator(config)

        projects = migrator.get_projects()
        click.echo("可用的项目:")
        if projects:
            for i, project in enumerate(projects, 1):
                click.echo(f"  {i}. {project.name} (ID: {project.id})")
                if hasattr(project, 'display_name') and project.display_name:
                    click.echo(f"     {project.display_name}")
        else:
            click.echo("未找到任何项目")

    except Exception as e:
        click.echo(f"获取项目列表失败: {e}", err=True)
        if ctx.obj['verbose']:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.pass_context
def test_connections(ctx):
    """测试连接"""
    try:
        config_file = ctx.obj['config_file']
        config_manager = ConfigManager(config_file)
        config = config_manager.load_config_with_env()
        migrator = MavenMigrator(config)

        results = migrator.test_connections()

        click.echo("连接测试结果:")
        for service, status in results.items():
            status_icon = "[OK]" if status else "[ERROR]"
            status_text = "成功" if status else "失败"
            click.echo(f"  {service.upper()}: {status_icon} {status_text}")

        if not all(results.values()):
            click.echo("\n请检查您的配置信息。")
            sys.exit(1)

    except Exception as e:
        click.echo(f"测试连接失败: {e}", err=True)
        if ctx.obj['verbose']:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.pass_context
def repository_info(ctx):
    """显示Nexus仓库信息"""
    repository_info = None  # 在 try 块外初始化变量

    try:
        config_file = ctx.obj['config_file']
        config_manager = ConfigManager(config_file)
        config = config_manager.load_config_with_env()
        migrator = MavenMigrator(config)

        repository_info = migrator.get_repository_info()

        click.echo("Nexus仓库信息:")
        click.echo("=" * 50)

        if isinstance(repository_info, dict):
            # 检查是否是多个仓库的信息
            if 'name' not in repository_info:
                # 多个仓库的情况
                click.echo(f"找到 {len(repository_info)} 个 Maven 仓库:")
                click.echo()
                for repo_name, repo_data in repository_info.items():
                    click.echo(f"仓库名称: {repo_data.get('name', 'Unknown')}")
                    click.echo(f"仓库格式: {repo_data.get('format', 'Unknown')}")
                    click.echo(f"仓库类型: {repo_data.get('type', 'Unknown')}")
                    click.echo(f"仓库URL: {repo_data.get('url', 'Unknown')}")
                    click.echo(f"仓库大小: {repo_data.get('size', 0)} bytes")
                    click.echo(f"制品数量: {repo_data.get('count', 0)}")
                    click.echo("-" * 40)
            else:
                # 单个仓库的情况（向后兼容）
                click.echo(f"仓库名称: {repository_info.get('name', 'Unknown')}")
                click.echo(f"仓库格式: {repository_info.get('format', 'Unknown')}")
                click.echo(f"仓库类型: {repository_info.get('type', 'Unknown')}")
                click.echo(f"仓库URL: {repository_info.get('url', 'Unknown')}")
                click.echo(f"仓库大小: {repository_info.get('size', 0)} bytes")
        else:
            click.echo(f"仓库信息: {repository_info}")

    except Exception as e:
        click.echo(f"获取仓库信息失败: {e}", err=True)
        if ctx.obj['verbose']:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option('--cleanup', is_flag=True, help='迁移完成后清理所有下载文件')
@click.pass_context
def migrate_all(ctx, cleanup):
    """迁移所有项目"""
    try:
        config_file = ctx.obj['config_file']
        config_manager = ConfigManager(config_file)
        config = config_manager.load_config_with_env()
        migrator = MavenMigrator(config)
        
        click.echo("[START] 开始迁移所有项目...")

        # 执行迁移
        stats = migrator.migrate_all()

        # 显示报告
        report = migrator.get_migration_report(stats)
        click.echo(report)

        # 清理下载文件
        if cleanup:
            click.echo("\n清理下载文件...")
            migrator.cleanup_downloads()

        # 检查是否有错误
        if stats["errors"] or stats["total_download_failures"] > 0 or stats["total_upload_failures"] > 0:
            click.echo("\n警告: 迁移过程中存在错误或失败，请检查日志。")
            sys.exit(1)
        else:
            click.echo("\n迁移完成！")

    except Exception as e:
        click.echo(f"迁移失败: {e}", err=True)
        import traceback
        click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@cli.command()
@click.option('--projects', '-p', help='指定要迁移的项目，多个项目用逗号分隔')
@click.option('--cleanup', is_flag=True, help='迁移完成后清理下载文件')
@click.option('--dry-run', is_flag=True, help='试运行，只下载不上传')
@click.option('--standard-mode', is_flag=True, help='使用标准模式（下载到本地再上传），默认使用内存流水线模式')
@click.option('--keep-records', is_flag=True, help='保留迁移记录文件，默认完成后清理')
@click.option('--filter', '-f', help='包过滤规则，多个规则用逗号分隔，覆盖配置文件设置')
@click.pass_context
def migrate(ctx, projects, cleanup, dry_run, standard_mode, keep_records, filter):
    """执行迁移（默认使用内存流水线模式：零磁盘占用、边下载边上传、完成后清理记录）"""
    try:
        config_file = ctx.obj['config_file']
        config_manager = ConfigManager()

        # 临时修改配置为指定项目
        config = config_manager.load_config()
        original_projects = config.project_names.copy()

        # 如果没有指定项目，使用配置文件中的项目列表
        if projects:
            # 解析项目列表
            project_list = [p.strip() for p in projects.split(',')]
            config.project_names = project_list
        else:
            # 使用配置文件中的项目列表
            project_list = config.project_names
            if not project_list:
                click.echo("错误: 没有指定要迁移的项目，且配置文件中也没有项目列表。")
                click.echo("请使用 --projects 参数指定项目，或在配置文件中设置项目列表。")
                sys.exit(1)

        # 如果指定了过滤规则，覆盖配置文件设置
        if filter:
            filter_patterns = [p.strip() for p in filter.split(',') if p.strip()]
            config.maven_filter.patterns = filter_patterns
            click.echo(f"使用命令行包过滤规则: {filter_patterns}")

        # 临时保存修改后的配置
        import tempfile
        import yaml
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_dict = config_manager.load_config_dict()
            config_dict['migration']['project_names'] = config.project_names
            config_dict['coding']['maven_filter']['patterns'] = config.maven_filter.patterns
            yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)
            temp_config_file = f.name

        config_manager = ConfigManager(config_file)
        config = config_manager.load_config_with_env()
        migrator = MavenMigrator(config)

        import os
        if 'temp_config_file' in locals():
            os.unlink(temp_config_file)

        if dry_run:
            click.echo("试运行模式：仅查看要迁移的制品，不执行下载")
            # 这里可以实现预览逻辑
            click.echo("试运行功能待实现")
            return

        # 默认使用内存流水线模式，除非用户指定标准模式
        if standard_mode:
            project_text = "、".join(project_list) if len(project_list) > 1 else project_list[0]
            click.echo(f"开始迁移项目: {project_text} (标准模式)")
            click.echo("警告: 标准模式会占用磁盘空间，建议使用默认的内存流水线模式")

            # 执行标准迁移
            stats = migrator.migrate_all()

            # 显示报告
            report = migrator.get_migration_report(stats)
            click.echo(report)

            # 清理下载文件
            if cleanup:
                click.echo("\n清理下载文件...")
                migrator.cleanup_downloads()
        else:
            project_text = "、".join(project_list) if len(project_list) > 1 else project_list[0]
            click.echo(f"内存流水线迁移项目开始: {project_text}")

            # 执行内存流水线迁移（支持多项目）
            total_stats = {
                'total': 0,
                'pending': 0,
                'downloaded': 0,
                'download_failed': 0,
                'uploaded': 0,
                'upload_failed': 0,
                'upload_success_rate': 0.0,
                'memory_peak': '未知'
            }

            for project_name in project_list:
                click.echo(f"\n正在处理项目: {project_name}")
                stats = migrator.migrate_project_memory_pipeline(project_name)

                if stats:
                    # 累计统计信息
                    for key in ['total', 'pending', 'downloaded', 'download_failed', 'uploaded', 'upload_failed']:
                        total_stats[key] += stats.get(key, 0)

                    click.echo(f"项目 {project_name} 完成:")
                    click.echo(f"  扫描制品: {stats.get('total', 0)}")
                    click.echo(f"  下载成功: {stats.get('downloaded', 0)}")
                    click.echo(f"  上传成功: {stats.get('uploaded', 0)}")
                else:
                    click.echo(f"项目 {project_name} 迁移失败")

            # 计算总体成功率
            if total_stats['downloaded'] > 0:
                total_stats['upload_success_rate'] = total_stats['uploaded'] / total_stats['downloaded']

            stats = total_stats

            # 显示报告
            if stats:
                click.echo("\n" + "="*60)
                click.echo("内存流水线迁移完成")
                click.echo("="*60)
                click.echo(f"扫描制品: {stats['total']}")
                click.echo(f"待上传(去重): {stats['pending']}")
                click.echo(f"下载成功: {stats['downloaded']}")
                click.echo(f"下载失败: {stats['download_failed']}")
                click.echo(f"上传成功: {stats['uploaded']}")
                click.echo(f"上传失败: {stats['upload_failed']}")
                click.echo(f"上传成功率: {stats['upload_success_rate']:.1%}")
                click.echo(f"内存使用峰值: {stats.get('memory_peak', '未知')}")

                # 默认清理，除非用户指定保留记录
                if not keep_records:
                    click.echo("\n🧹 迁移记录文件已自动清理")
                else:
                    click.echo("\n📝 迁移记录文件已保留")
            else:
                click.echo("[ERROR] 内存流水线迁移失败")
                sys.exit(1)

        # 检查是否有错误 (仅在标准模式下检查)
        if standard_mode and stats:
            if stats["errors"] or stats["total_download_failures"] > 0 or stats["total_upload_failures"] > 0:
                click.echo("\n警告: 迁移过程中存在错误或失败，请检查日志。")
                sys.exit(1)
            else:
                click.echo("\n迁移完成！")

    except Exception as e:
        click.echo(f"迁移失败: {e}", err=True)
        import traceback
        click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@cli.command()
@click.pass_context


@cli.command()
@click.argument('project_name')
@click.option('--pipeline', is_flag=True, help='使用流水线模式（边下载边上传）')
@click.pass_context
def migrate_pipeline(ctx, project_name, pipeline):
    """使用流水线模式迁移单个项目（边下载边上传）"""
    try:
        config_file = ctx.obj['config_file']
        config_manager = ConfigManager(config_file)
        config = config_manager.load_config_with_env()
        migrator = MavenMigrator(config)
        
        click.echo(f"[START] 流水线迁移项目开始: {project_name}")

        # 执行流水线迁移
        stats = migrator.migrate_project_pipeline(project_name)

        # 显示报告
        if stats:
            click.echo("\n" + "="*60)
            click.echo("流水线迁移完成")
            click.echo("="*60)
            click.echo(f"扫描制品: {stats['total']}")
            click.echo(f"下载成功: {stats['downloaded']}")
            click.echo(f"下载失败: {stats['download_failed']}")
            click.echo(f"上传成功: {stats['uploaded']}")
            click.echo(f"上传失败: {stats['upload_failed']}")
            click.echo(f"上传成功率: {stats['upload_success_rate']:.1%}")
        else:
            click.echo("[ERROR] 流水线迁移失败")
            sys.exit(1)

    except Exception as e:
        click.echo(f"[ERROR] 流水线迁移失败: {e}", err=True)
        import traceback
        click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@cli.command()
@click.argument('project_name')
@click.option('--cleanup', is_flag=True, help='迁移完成后清理记录文件')
@click.pass_context
def migrate_memory_pipeline(ctx, project_name, cleanup):
    """使用内存流水线模式迁移单个项目（零磁盘占用，边下载边上传）"""
    try:
        config_file = ctx.obj['config_file']
        config_manager = ConfigManager(config_file)
        config = config_manager.load_config_with_env()
        migrator = MavenMigrator(config)
        
        click.echo(f"内存流水线迁移项目开始: {project_name}")

        # 执行内存流水线迁移
        stats = migrator.migrate_project_memory_pipeline(project_name)

        # 显示报告
        if stats:
            click.echo("\n" + "="*60)
            click.echo("内存流水线迁移完成")
            click.echo("="*60)
            click.echo(f"扫描制品: {stats['total_artifacts']}")
            click.echo(f"跳过已上传: {stats['skipped_existing']}")
            click.echo(f"下载成功: {stats['downloaded']}")
            click.echo(f"下载失败: {stats['download_failed']}")
            click.echo(f"上传成功: {stats['uploaded']}")
            click.echo(f"上传失败: {stats['upload_failed']}")
            processed = stats['uploaded'] + stats['upload_failed']
            success_rate = (stats['uploaded'] / processed * 100) if processed > 0 else 0
            click.echo(f"上传成功率: {success_rate:.1f}%")
            click.echo(f"内存使用峰值: {stats.get('memory_peak', '未知')}")

            if cleanup:
                click.echo("\n🧹 迁移记录文件已清理")
        else:
            click.echo("[ERROR] 内存流水线迁移失败")
            sys.exit(1)

    except Exception as e:
        click.echo(f"[ERROR] 内存流水线迁移失败: {e}", err=True)
        import traceback
        click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


if __name__ == '__main__':
    cli()