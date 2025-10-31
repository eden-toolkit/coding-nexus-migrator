"""
主迁移模块
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from .config import ConfigManager
from .coding_client import CodingClient
from .downloader import MavenDownloader
from .nexus_uploader import NexusUploader
from .pipeline_migrator import PipelineMigrator
from .memory_pipeline_migrator import MemoryPipelineMigrator
from .models import MigrationConfig


logger = logging.getLogger(__name__)


class MavenMigrator:
    """Maven 制品迁移器"""

    def __init__(self, config: MigrationConfig):
        """
        初始化迁移器

        Args:
            config: 迁移配置对象
        """
        self.config = config

    def get_projects(self) -> List[Any]:
        """
        获取所有可用的项目列表

        Returns:
            项目列表
        """
        if not self.config:
            raise ValueError("Migrator not properly initialized")

        try:
            # 创建 CODING 客户端
            coding_client = CodingClient(
                self.config.coding_token,
                self.config.coding_team_id,
                self.config.maven_repositories,
                self.config.pagination,
                self.config.performance.max_workers,
                requests_per_second=self.config.rate_limit.requests_per_second
            )

            # 获取所有项目
            projects = coding_client.get_all_projects()
            return projects

        except Exception as e:
            logger.error(f"Failed to get projects: {e}")
            raise

    def get_repository_info(self) -> Dict[str, Any]:
        """
        获取 Nexus 仓库信息

        Returns:
            仓库信息
        """
        if not self.config:
            raise ValueError("Migrator not properly initialized")

        try:
            # 创建 Nexus 上传器
            nexus_uploader = NexusUploader(self.config)

            # 获取仓库信息
            repository_info = nexus_uploader.get_repository_info()
            return repository_info

        except Exception as e:
            logger.error(f"Failed to get repository info: {e}")
            raise

    def migrate_all(self, cleanup: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        """
        迁移所有配置的项目

        Args:
            cleanup: 迁移完成后是否清理下载文件
            dry_run: 是否为试运行模式

        Returns:
            迁移结果统计
        """
        if not self.config:
            raise ValueError("Migrator not properly initialized")

        logger.info("Starting full migration process")

        # 初始化客户端
        coding_client = CodingClient(
            self.config.coding_token,
            self.config.coding_team_id,
            self.config.maven_repositories,
            self.config.pagination,
            self.config.performance.max_workers,
            requests_per_second=self.config.rate_limit.requests_per_second
        )
        downloader = MavenDownloader(coding_client, self.config)
        nexus_uploader = NexusUploader(self.config)

        # 测试 Nexus 连接
        if not nexus_uploader.test_connection():
            raise ConnectionError("Failed to connect to Nexus. Please check your configuration.")

        # 获取要迁移的项目列表
        project_names = self.config.project_names
        if not project_names:
            # 如果没有指定项目，获取所有项目
            all_projects = coding_client.get_all_projects()
            project_names = [project.name for project in all_projects]

        logger.info(f"Projects to migrate: {project_names}")

        # 总体统计
        total_stats = {
            "projects": {},
            "total_artifacts_downloaded": 0,
            "total_artifacts_uploaded": 0,
            "total_download_failures": 0,
            "total_upload_failures": 0,
            "errors": []
        }

        # 逐个项目迁移
        for project_name in project_names:
            try:
                logger.info(f"Starting migration for project: {project_name}")

                project_stats = self.migrate_project(project_name, coding_client, downloader, nexus_uploader)
                total_stats["projects"][project_name] = project_stats

                total_stats["total_artifacts_downloaded"] += project_stats.get("downloaded", 0)
                total_stats["total_artifacts_uploaded"] += project_stats.get("uploaded", 0)
                total_stats["total_download_failures"] += project_stats.get("download_failures", 0)
                total_stats["total_upload_failures"] += project_stats.get("upload_failures", 0)

                logger.info(f"Completed migration for project: {project_name}")

            except Exception as e:
                error_msg = f"Failed to migrate project {project_name}: {e}"
                logger.error(error_msg)
                total_stats["errors"].append(error_msg)

        logger.info("Full migration process completed")
        return total_stats

    def migrate_project(self, project_name: str, coding_client: CodingClient,
                       downloader: MavenDownloader, nexus_uploader: NexusUploader) -> Dict[str, Any]:
        """
        迁移单个项目

        Args:
            project_name: 项目名称
            coding_client: CODING 客户端
            downloader: 下载器
            nexus_uploader: 上传器

        Returns:
            项目迁移结果
        """
        project_stats = {
            "downloaded": 0,
            "download_failures": 0,
            "uploaded": 0,
            "upload_failures": 0,
            "repositories": {}
        }

        try:
            # 第一步：下载制品
            logger.info(f"Step 1: Downloading artifacts from project: {project_name}")
            download_stats = downloader.download_project_artifacts(project_name)

            project_stats["downloaded"] = download_stats.get("downloaded", 0)
            project_stats["download_failures"] = download_stats.get("failed", 0)

            logger.info(f"Download completed for {project_name}: {project_stats['downloaded']} downloaded, {project_stats['download_failures']} failed")

            # 第二步：上传制品
            if project_stats["downloaded"] > 0:
                logger.info(f"Step 2: Uploading artifacts to Nexus for project: {project_name}")

                download_path = Path(self.config.download_path)
                upload_stats = nexus_uploader.upload_directory(download_path, self.config.batch_size)

                project_stats["uploaded"] = upload_stats.get("uploaded", 0)
                project_stats["upload_failures"] = upload_stats.get("failed", 0)
                project_stats["skipped"] = upload_stats.get("skipped", 0)

                logger.info(f"Upload completed for {project_name}: {project_stats['uploaded']} uploaded, {project_stats['upload_failures']} failed, {project_stats['skipped']} skipped")

            return project_stats

        except Exception as e:
            error_msg = f"Error migrating project {project_name}: {e}"
            logger.error(error_msg)
            project_stats["error"] = error_msg
            return project_stats

    def migrate_project_cli(self, project_name: str, cleanup: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        """
        迁移单个项目（CLI版本）

        Args:
            project_name: 项目名称
            cleanup: 迁移完成后是否清理下载文件
            dry_run: 是否为试运行模式

        Returns:
            项目迁移结果
        """
        if not self.config:
            raise ValueError("Migrator not properly initialized")

        try:
            # 初始化客户端
            coding_client = CodingClient(
                self.config.coding_token,
                self.config.coding_team_id,
                self.config.maven_repositories,
                self.config.pagination,
                self.config.performance.max_workers,
                requests_per_second=self.config.rate_limit.requests_per_second
            )
            downloader = MavenDownloader(coding_client, self.config)
            nexus_uploader = NexusUploader(self.config)

            # 测试 Nexus 连接
            if not nexus_uploader.test_connection():
                raise ConnectionError("Failed to connect to Nexus. Please check your configuration.")

            if dry_run:
                logger.info(f"试运行模式：只检查项目 {project_name}，不执行实际迁移")
                return {
                    "project": project_name,
                    "dry_run": True,
                    "status": "success"
                }

            # 执行迁移
            return self.migrate_project(project_name, coding_client, downloader, nexus_uploader)

        except Exception as e:
            logger.error(f"Failed to migrate project {project_name}: {e}")
            return {
                "project": project_name,
                "error": str(e),
                "status": "failed"
            }

    def test_connections(self) -> Dict[str, bool]:
        """
        测试所有连接

        Returns:
            连接测试结果
        """
        if not self.config:
            raise ValueError("Migrator not properly initialized")

        results = {
            "coding": False,
            "nexus": False
        }

        # 测试 CODING 连接
        try:
            coding_client = CodingClient(
                self.config.coding_token,
                self.config.coding_team_id,
                self.config.maven_repositories,
                requests_per_second=self.config.rate_limit.requests_per_second
            )
            projects = coding_client.get_projects(1, 1)  # 只获取一个项目测试连接
            results["coding"] = True
            logger.info("CODING connection test successful")
        except Exception as e:
            logger.error(f"CODING connection test failed: {e}")

        # 测试 Nexus 连接
        try:
            nexus_uploader = NexusUploader(self.config)
            results["nexus"] = nexus_uploader.test_connection()
        except Exception as e:
            logger.error(f"Nexus connection test failed: {e}")

        return results

    def cleanup_downloads(self) -> None:
        """
        清理下载的文件
        """
        if not self.config:
            raise ValueError("Migrator not properly initialized")

        download_path = Path(self.config.download_path)

        if download_path.exists():
            import shutil
            shutil.rmtree(download_path)
            logger.info(f"Cleaned up download directory: {download_path}")

    def get_migration_report(self, stats: Dict[str, Any]) -> str:
        """
        生成迁移报告

        Args:
            stats: 迁移统计数据

        Returns:
            格式化的迁移报告
        """
        report = []
        report.append("=" * 60)
        report.append("CODING Maven 制品库迁移报告")
        report.append("=" * 60)

        # 总体统计
        report.append("\n总体统计:")
        report.append(f"  总下载制品数: {stats['total_artifacts_downloaded']}")
        report.append(f"  总上传制品数: {stats['total_artifacts_uploaded']}")
        report.append(f"  下载失败数: {stats['total_download_failures']}")
        report.append(f"  上传失败数: {stats['total_upload_failures']}")

        # 项目详情
        report.append("\n项目详情:")
        for project_name, project_stats in stats["projects"].items():
            report.append(f"  {project_name}:")
            report.append(f"    下载: {project_stats.get('downloaded', 0)} 成功, {project_stats.get('download_failures', 0)} 失败")
            report.append(f"    上传: {project_stats.get('uploaded', 0)} 成功, {project_stats.get('upload_failures', 0)} 失败")
            if 'skipped' in project_stats:
                report.append(f"    跳过: {project_stats.get('skipped', 0)}")

        # 错误信息
        if stats["errors"]:
            report.append("\n错误信息:")
            for error in stats["errors"]:
                report.append(f"  - {error}")

        report.append("\n" + "=" * 60)

        return "\n".join(report)

    def migrate_project_pipeline(self, project_name: str) -> Dict[str, Any]:
        """
        使用流水线模式迁移单个项目（边下载边上传）

        Args:
            project_name: 项目名称

        Returns:
            迁移结果统计
        """
        if not self.config:
            raise ValueError("Migrator not properly initialized")

        logger.info(f"Starting pipeline migration for project: {project_name}")

        # 测试连接
        if not self._test_connections():
            raise ConnectionError("Failed to establish connections. Please check your configuration.")

        # 获取项目信息
        project_info = self._get_project_by_name(project_name)
        if not project_info:
            raise ValueError(f"Project '{project_name}' not found")

        project_id = project_info['id']

        # 创建流水线迁移器
        pipeline_migrator = PipelineMigrator(self.config)

        # 执行流水线迁移
        stats = pipeline_migrator.migrate_project(project_id, project_name)

        return stats

    def migrate_project_memory_pipeline(self, project_name: str) -> Dict[str, Any]:
        """
        使用内存流水线模式迁移单个项目（零磁盘占用）

        Args:
            project_name: 项目名称

        Returns:
            迁移结果统计
        """
        if not self.config:
            raise ValueError("Migrator not properly initialized")

        logger.info(f"Starting memory pipeline migration for project: {project_name}")

        # 测试连接
        if not self._test_connections():
            raise ConnectionError("Failed to establish connections. Please check your configuration.")

        # 获取项目信息
        project_info = self._get_project_by_name(project_name)
        if not project_info:
            raise ValueError(f"Project '{project_name}' not found")

        project_id = project_info['id']

        # 创建内存流水线迁移器
        memory_migrator = MemoryPipelineMigrator(self.config)

        # 执行内存流水线迁移
        stats = memory_migrator.migrate_project(project_id, project_name)

        return stats

    def _test_connections(self) -> bool:
        """测试连接"""
        try:
            # 初始化客户端（如果还没有初始化）
            if not hasattr(self, 'coding_client'):
                self.coding_client = CodingClient(
                    self.config.coding_token,
                    self.config.coding_team_id,
                    self.config.maven_repositories,
                    self.config.pagination,
                    self.config.performance.max_workers,
                    requests_per_second=self.config.rate_limit.requests_per_second
                )

            if not hasattr(self, 'nexus_uploader'):
                self.nexus_uploader = NexusUploader(self.config)

            # 测试 CODING 连接
            projects = self.coding_client.get_all_projects()
            if not projects:
                logger.error("Failed to connect to CODING API")
                return False

            # 测试 Nexus 连接
            nexus_ok = self.nexus_uploader.test_connection()
            if not nexus_ok:
                logger.error("Failed to connect to Nexus")
                return False

            logger.info("All connections test successful")
            return True

        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    def _get_project_by_name(self, project_name: str) -> Optional[Dict[str, Any]]:
        """根据项目名称获取项目信息"""
        try:
            if not hasattr(self, 'coding_client'):
                self.coding_client = CodingClient(
                    self.config.coding_token,
                    self.config.coding_team_id,
                    self.config.maven_repositories,
                    self.config.pagination,
                    self.config.performance.max_workers,
                    requests_per_second=self.config.rate_limit.requests_per_second
                )

            projects = self.coding_client.get_all_projects()
            for project in projects:
                if project.name == project_name:
                    return {
                        'id': project.id,
                        'name': project.name,
                        'display_name': getattr(project, 'display_name', project.name)
                    }
            return None
        except Exception as e:
            logger.error(f"Failed to get project by name {project_name}: {e}")
            return None