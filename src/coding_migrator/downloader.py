"""
Maven 制品下载器
"""

import os
import logging
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional
from tqdm import tqdm
from .coding_client import CodingClient
from .models import MavenArtifact, MigrationConfig


logger = logging.getLogger(__name__)


class MavenDownloader:
    """Maven 制品下载器"""

    def __init__(self, coding_client: CodingClient, config: MigrationConfig):
        """
        初始化下载器

        Args:
            coding_client: CODING API 客户端
            config: 迁移配置
        """
        self.client = coding_client
        self.config = config
        self.download_path = Path(config.download_path)
        self.download_path.mkdir(parents=True, exist_ok=True)

    def download_project_artifacts(self, project_name: str) -> Dict[str, Any]:
        """
        下载指定项目的所有 Maven 制品

        Args:
            project_name: 项目名称

        Returns:
            下载结果统计
        """
        logger.info(f"Starting download for project: {project_name}")

        # 获取项目信息
        project = self.client.get_project_by_name(project_name)
        if not project:
            raise ValueError(f"Project not found: {project_name}")

        logger.info(f"Found project: {project.display_name} (ID: {project.id})")

        # 获取制品仓库列表
        repositories = self.client.get_artifact_repositories(project.id)

        maven_repos = [repo for repo in repositories if repo.get('Type') == 3 or repo.get('Type') == 'maven']

        if not maven_repos:
            logger.warning(f"No Maven repositories found in project: {project_name}")
            # 尝试使用其他类型的仓库（可能 CODING 使用不同的类型标识）
            alternative_repos = [repo for repo in repositories if 'maven' in repo.get('Name', '').lower()]
            if alternative_repos:
                logger.info(f"Found potential Maven repositories by name: {[repo.get('Name') for repo in alternative_repos]}")
                maven_repos = alternative_repos
            else:
                # 如果还是找不到，尝试使用第一个仓库作为默认
                if repositories:
                    logger.warning(f"Using first repository as fallback: {repositories[0].get('Name', 'unknown')}")
                    maven_repos = [repositories[0]]
                else:
                    # 即使没有找到仓库，也尝试使用标准的 Maven 仓库名称
                    logger.warning("No repositories found, but will try standard Maven repository names")
                    maven_repos = [{"Name": "releases", "Type": 3}, {"Name": "snapshots", "Type": 3}]

        # 统计信息
        stats = {
            "total_artifacts": 0,
            "downloaded": 0,
            "failed": 0,
            "failed_files": []
        }

        # 为每个 Maven 仓库下载制品
        for repo in maven_repos:
            repo_name = repo.get('Name', '')
            logger.info(f"Processing repository: {repo_name}")

            repo_stats = self.download_repository_artifacts(project.id, repo_name)
            stats["total_artifacts"] += repo_stats["total_artifacts"]
            stats["downloaded"] += repo_stats["downloaded"]
            stats["failed"] += repo_stats["failed"]
            stats["failed_files"].extend(repo_stats["failed_files"])

        return stats

    def download_repository_artifacts(self, project_id: int, repository_name: str) -> Dict[str, Any]:
        """
        下载指定仓库的所有 Maven 制品

        Args:
            project_id: 项目 ID
            repository_name: 仓库名称

        Returns:
            下载结果统计
        """
        logger.info(f"Downloading artifacts from repository: {repository_name}")

        try:
            # 获取所有制品（现在分页在get_maven_artifacts中处理）
            logger.info(f"Fetching all artifacts from repository: {repository_name}")
            all_artifacts = self.client.get_maven_artifacts(project_id, repository_name, self.config.maven_filter)

            logger.info(f"Found {len(all_artifacts)} artifacts in repository: {repository_name}")

            # 显示发现的制品类型统计
            if all_artifacts:
                jar_count = sum(1 for a in all_artifacts if a.packaging == 'jar')
                pom_count = sum(1 for a in all_artifacts if a.packaging == 'pom')
                logger.info(f"📊 Artifact types: {jar_count} JAR files, {pom_count} POM files")

                # 过滤完全相同的制品（保留所有版本）
                unique_artifacts = self._filter_duplicate_files(all_artifacts)
                logger.info(f"After filtering duplicate files: {len(unique_artifacts)} unique artifacts")

                # 并发下载
                stats = self._download_artifacts_parallel(project_id, repository_name, unique_artifacts)
                return stats
            else:
                logger.warning(f"No artifacts found in repository: {repository_name}")
                return {"total_artifacts": 0, "downloaded": 0, "failed": 0, "failed_files": []}

        except Exception as e:
            logger.error(f"Error downloading artifacts from repository {repository_name}: {e}")
            return {"total_artifacts": 0, "downloaded": 0, "failed": 0, "failed_files": []}

    def _filter_duplicate_files(self, artifacts: List[MavenArtifact]) -> List[MavenArtifact]:
        """
        过滤完全相同的制品文件，保留所有版本

        Args:
            artifacts: 原始制品列表

        Returns:
            过滤后的制品列表
        """
        seen_files = set()
        unique_artifacts = []

        for artifact in artifacts:
            # 使用完整的坐标（包括版本）作为唯一标识
            file_key = f"{artifact.group_id}:{artifact.artifact_id}:{artifact.version}:{artifact.packaging}"

            if file_key not in seen_files:
                seen_files.add(file_key)
                unique_artifacts.append(artifact)

        return unique_artifacts

    def _filter_unique_artifacts(self, artifacts: List[MavenArtifact]) -> List[MavenArtifact]:
        """
        过滤重复的制品，只保留每个 artifact_id 的最新版本

        Args:
            artifacts: 原始制品列表

        Returns:
            过滤后的制品列表
        """
        artifact_map = {}

        for artifact in artifacts:
            key = f"{artifact.group_id}:{artifact.artifact_id}:{artifact.packaging}"

            if key not in artifact_map or self._is_newer_version(artifact.version, artifact_map[key].version):
                artifact_map[key] = artifact

        return list(artifact_map.values())

    def _is_newer_version(self, version1: str, version2: str) -> bool:
        """
        比较版本号，判断 version1 是否比 version2 更新

        Args:
            version1: 版本1
            version2: 版本2

        Returns:
            version1 是否比 version2 更新
        """
        try:
            # 简单的版本号比较，可以扩展为更复杂的语义版本比较
            v1_parts = [int(x) for x in version1.split('.') if x.isdigit()]
            v2_parts = [int(x) for x in version2.split('.') if x.isdigit()]

            # 补齐长度
            max_len = max(len(v1_parts), len(v2_parts))
            v1_parts.extend([0] * (max_len - len(v1_parts)))
            v2_parts.extend([0] * (max_len - len(v2_parts)))

            return v1_parts > v2_parts

        except (ValueError, AttributeError):
            # 如果无法解析为数字，则使用字符串比较
            return version1 > version2

    def _download_artifacts_parallel(self, project_id: int, repository_name: str, artifacts: List[MavenArtifact]) -> Dict[str, Any]:
        """
        并发下载制品

        Args:
            project_id: 项目 ID
            repository_name: 仓库名称
            artifacts: 制品列表

        Returns:
            下载结果统计
        """
        stats = {
            "total_artifacts": len(artifacts),
            "downloaded": 0,
            "failed": 0,
            "failed_files": []
        }

        # 创建项目下载目录
        project_download_path = self.download_path / repository_name
        project_download_path.mkdir(parents=True, exist_ok=True)

        def download_single_artifact(artifact: MavenArtifact) -> bool:
            """下载单个制品"""
            try:
                # 构建本地文件路径
                local_path = self._build_local_path(project_download_path, artifact)

                # 如果文件已存在，跳过
                if local_path.exists() and local_path.stat().st_size > 0:
                    logger.debug(f"File already exists, skipping: {local_path}")
                    return True

                # 创建目录
                local_path.parent.mkdir(parents=True, exist_ok=True)

                # 下载文件，如果存在 download_url 则使用它
                download_url = getattr(artifact, 'download_url', None)
                success = self.client.download_artifact(
                    project_id,
                    repository_name,
                    artifact.file_path,
                    str(local_path),
                    download_url
                )

                if success:
                    logger.debug(f"Successfully downloaded: {artifact.file_path}")
                else:
                    logger.warning(f"Failed to download: {artifact.file_path}")

                return success

            except Exception as e:
                logger.error(f"Error downloading {artifact.file_path}: {e}")
                return False

        # 使用线程池并发下载
        with tqdm(total=len(artifacts), desc=f"Downloading {repository_name}") as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.parallel_downloads) as executor:
                # 提交所有下载任务
                future_to_artifact = {
                    executor.submit(download_single_artifact, artifact): artifact
                    for artifact in artifacts
                }

                # 处理完成的任务
                for future in concurrent.futures.as_completed(future_to_artifact):
                    artifact = future_to_artifact[future]

                    try:
                        success = future.result()
                        if success:
                            stats["downloaded"] += 1
                        else:
                            stats["failed"] += 1
                            stats["failed_files"].append(artifact.file_path)

                    except Exception as e:
                        logger.error(f"Download failed for {artifact.file_path}: {e}")
                        stats["failed"] += 1
                        stats["failed_files"].append(artifact.file_path)

                    pbar.update(1)

        return stats

    def _build_local_path(self, base_path: Path, artifact: MavenArtifact) -> Path:
        """
        构建本地文件路径，保持 Maven 仓库结构

        Args:
            base_path: 基础路径
            artifact: Maven 制品

        Returns:
            本地文件路径
        """
        # 转换 group_id 的点号为路径分隔符
        group_path = artifact.group_id.replace('.', '/')

        # 构建文件名
        if artifact.packaging == "pom":
            filename = f"{artifact.artifact_id}-{artifact.version}.pom"
        elif artifact.packaging == "jar" and artifact.file_path.endswith('-sources.jar'):
            filename = f"{artifact.artifact_id}-{artifact.version}-sources.jar"
        else:
            filename = f"{artifact.artifact_id}-{artifact.version}.{artifact.packaging}"

        return base_path / group_path / artifact.artifact_id / artifact.version / filename

    def get_downloaded_files(self) -> List[Path]:
        """
        获取已下载的文件列表

        Returns:
            已下载文件路径列表
        """
        downloaded_files = []

        for file_path in self.download_path.rglob('*'):
            if file_path.is_file():
                downloaded_files.append(file_path)

        return downloaded_files

    def download_repository_artifacts_with_fallback(self, project_id: int, repository_name: str) -> Dict[str, Any]:
        """
        下载仓库制品

        Args:
            project_id: 项目 ID
            repository_name: 仓库名称

        Returns:
            下载结果统计
        """
        logger.info(f"Downloading artifacts from repository: {repository_name}")

        try:
            repo_stats = self.download_repository_artifacts(project_id, repository_name)
            logger.info(f"Found {repo_stats.get('total_artifacts', 0)} artifacts in repository: {repository_name}")
            return repo_stats

        except Exception as e:
            logger.warning(f"Failed to download artifacts from repository {repository_name}: {e}")
            return {"total_artifacts": 0, "downloaded": 0, "failed": 0, "failed_files": []}