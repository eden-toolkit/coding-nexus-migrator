"""
Nexus 上传器
"""

import os
import re
import logging
import requests
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
from tqdm import tqdm
from requests.auth import HTTPBasicAuth
from .models import MigrationConfig, MavenArtifact


logger = logging.getLogger(__name__)


class NexusUploader:
    """Nexus 上传器"""

    def __init__(self, config: MigrationConfig):
        """
        初始化上传器

        Args:
            config: 迁移配置
        """
        self.config = config
        self.nexus_url = config.nexus_url.rstrip('/')
        self.repository = config.nexus_repository
        self.auth = HTTPBasicAuth(config.nexus_username, config.nexus_password)
        self.session = requests.Session()
        self.session.auth = self.auth

        # 缓存仓库信息
        self.repositories_cache = None
        self.snapshot_repo = config.nexus_snapshot_repository
        self.releases_repo = config.nexus_releases_repository

    def is_snapshot_version(self, version: str) -> bool:
        """
        判断是否为 SNAPSHOT 版本

        Args:
            version: 版本号

        Returns:
            是否为 SNAPSHOT 版本
        """
        return version.upper().endswith('-SNAPSHOT')

    def determine_repository(self, version: str) -> str:
        """
        根据版本号确定目标仓库

        Args:
            version: 版本号

        Returns:
            目标仓库名称
        """
        if self.is_snapshot_version(version):
            # 如果是 SNAPSHOT 版本，优先使用配置的快照仓库
            if self.snapshot_repo:
                return self.snapshot_repo

            # 尝试自动检测快照仓库
            auto_snapshot_repo = self._find_snapshot_repository()
            if auto_snapshot_repo:
                self.snapshot_repo = auto_snapshot_repo
                return auto_snapshot_repo

            # 如果没有找到，使用默认配置
            logger.warning(f"No snapshot repository found, using default: {self.repository}")
            return self.repository
        else:
            # 如果是发布版本，优先使用配置的发布仓库
            if self.releases_repo:
                return self.releases_repo

            # 尝试自动检测发布仓库
            auto_releases_repo = self._find_releases_repository()
            if auto_releases_repo:
                self.releases_repo = auto_releases_repo
                return auto_releases_repo

            # 如果没有找到，使用默认配置
            logger.warning(f"No releases repository found, using default: {self.repository}")
            return self.repository

    def _find_snapshot_repository(self) -> Optional[str]:
        """
        查找快照仓库

        Returns:
            快照仓库名称或 None
        """
        repositories = self._get_all_repositories()

        # 优先查找名称包含 snapshot 的仓库
        for repo in repositories:
            repo_name = repo.get('name', '').lower()
            if 'snapshot' in repo_name and repo.get('format') == 'maven2':
                return repo.get('name')

        # 如果没找到，尝试查找包含 snap 的仓库
        for repo in repositories:
            repo_name = repo.get('name', '').lower()
            if 'snap' in repo_name and repo.get('format') == 'maven2':
                return repo.get('name')

        return None

    def _find_releases_repository(self) -> Optional[str]:
        """
        查找发布仓库

        Returns:
            发布仓库名称或 None
        """
        repositories = self._get_all_repositories()

        # 优先查找名称包含 release 的仓库
        for repo in repositories:
            repo_name = repo.get('name', '').lower()
            if 'release' in repo_name and repo.get('format') == 'maven2':
                return repo.get('name')

        # 如果没找到，尝试查找包含 hosted 的仓库
        for repo in repositories:
            repo_name = repo.get('name', '').lower()
            if 'hosted' in repo_name and repo.get('format') == 'maven2':
                return repo.get('name')

        return None

    def _get_all_repositories(self) -> List[Dict[str, Any]]:
        """
        获取所有仓库列表

        Returns:
            仓库列表
        """
        if self.repositories_cache is None:
            try:
                repositories_url = f"{self.nexus_url}/service/rest/v1/repositories"
                response = self.session.get(repositories_url)

                if response.status_code == 200:
                    self.repositories_cache = response.json()
                    logger.debug(f"Retrieved {len(self.repositories_cache)} repositories from Nexus")
                else:
                    logger.error(f"Failed to retrieve repositories: {response.status_code}")
                    self.repositories_cache = []

            except Exception as e:
                logger.error(f"Error retrieving repositories: {e}")
                self.repositories_cache = []

        return self.repositories_cache

    def _get_content_type(self, file_extension: str) -> str:
        """
        根据文件扩展名确定正确的 Content-Type

        Args:
            file_extension: 文件扩展名（包含点号）

        Returns:
            Content-Type 字符串
        """
        extension = file_extension.lower()

        # Maven 制品文件的 Content-Type 映射
        content_type_map = {
            '.jar': 'application/java-archive',
            '.pom': 'text/xml',
            '.xml': 'text/xml',
            '.war': 'application/java-archive',
            '.ear': 'application/java-archive',
            '.zip': 'application/zip',
            '.tar': 'application/x-tar',
            '.gz': 'application/gzip',
            '.txt': 'text/plain',
            '.md5': 'text/plain',
            '.sha1': 'text/plain',
            '.asc': 'text/plain',
            '.json': 'application/json',
            '.properties': 'text/plain',
            '.yml': 'text/yaml',
            '.yaml': 'text/yaml'
        }

        return content_type_map.get(extension, 'application/octet-stream')

    def upload_file(self, file_path: Path, maven_path: str) -> Dict[str, Any]:
        """
        上传单个文件到 Nexus (使用 PUT 方法)

        Args:
            file_path: 本地文件路径
            maven_path: Maven 仓库中的路径

        Returns:
            上传结果
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # 构建仓库路径
        repository_path = maven_path.replace('\\', '/')

        try:
            # 读取文件内容
            with open(file_path, 'rb') as f:
                file_content = f.read()

            # 构建 Maven 坐标
            parts = repository_path.split('/')
            if len(parts) >= 4:
                group_id = '.'.join(parts[:-3])
                artifact_id = parts[-3]
                version = parts[-2]
                filename = parts[-1]

                # 根据版本号确定目标仓库
                target_repository = self.determine_repository(version)

                # 构建 PUT URL: /repository/{repo-name}/{group-path}/{artifact}/{version}/{filename}
                group_path = group_id.replace('.', '/')
                put_url = f"{self.nexus_url}/repository/{target_repository}/{group_path}/{artifact_id}/{version}/{filename}"

                # 根据文件扩展名确定正确的 Content-Type
                content_type = self._get_content_type(file_path.suffix)

                headers = {
                    'Content-Type': content_type,
                    'Content-Length': str(len(file_content))
                }

                logger.debug(f"Uploading {file_path.name} to repository: {target_repository} using PUT method")
                logger.debug(f"PUT URL: {put_url}")
                logger.debug(f"File size: {len(file_content)} bytes")

                # 发送 PUT 请求上传文件
                response = self.session.put(put_url, data=file_content, headers=headers)

                # 调试：打印更详细的响应信息
                if response.status_code not in [201, 204]:
                    logger.warning(f"Unexpected status code {response.status_code} for PUT request")
                    logger.warning(f"Response content: {response.text[:500]}")  # 只显示前500个字符

                if response.status_code in [201, 204]:
                    # 显示更清晰的上传信息
                    logger.info(f"[OK] UPLOAD: {group_id}:{artifact_id}:{version} -> {target_repository}")
                    logger.info(f"   File: {filename}")
                    return {
                        "success": True,
                        "file_path": str(file_path),
                        "maven_path": repository_path,
                        "repository": target_repository,
                        "status_code": response.status_code
                    }
                else:
                    error_text = response.text
                    try:
                        # 尝试解析JSON错误信息
                        error_json = response.json()
                        error_detail = error_json.get('error_details', error_text)
                    except:
                        error_detail = error_text

                    logger.error(f"Failed to upload {file_path}: {response.status_code} - {error_detail}")
                    logger.error(f"Upload URL: {put_url}")
                    logger.error(f"Repository: {target_repository}")
                    logger.error(f"Maven coordinates: {group_id}:{artifact_id}:{version}")
                    logger.error(f"Group path: {group_path}")
                    logger.error(f"Filename: {filename}")
                    logger.error(f"Content-Type: {content_type}")
                    logger.error(f"Response headers: {dict(response.headers)}")

                    return {
                        "success": False,
                        "file_path": str(file_path),
                        "maven_path": repository_path,
                        "repository": target_repository,
                        "status_code": response.status_code,
                        "error": error_detail
                    }
            else:
                raise ValueError(f"Invalid Maven path format: {repository_path}")

        except Exception as e:
            logger.error(f"Error uploading {file_path}: {e}")
            return {
                "success": False,
                "file_path": str(file_path),
                "maven_path": repository_path,
                "error": str(e)
            }

    def upload_directory(self, directory_path: Path, batch_size: Optional[int] = None) -> Dict[str, Any]:
        """
        上传目录中的所有 Maven 制品到 Nexus

        Args:
            directory_path: 本地目录路径
            batch_size: 批处理大小

        Returns:
            上传结果统计
        """
        if not directory_path.exists() or not directory_path.is_dir():
            raise ValueError(f"Directory not found: {directory_path}")

        batch_size = batch_size or self.config.batch_size

        # 获取所有需要上传的文件
        files_to_upload = []
        for file_path in directory_path.rglob('*'):
            if file_path.is_file():
                # 转换为 Maven 路径
                relative_path = file_path.relative_to(directory_path)
                maven_path = str(relative_path)
                files_to_upload.append((file_path, maven_path))

        logger.info(f"Found {len(files_to_upload)} files to upload")

        # 统计信息
        stats = {
            "total_files": len(files_to_upload),
            "uploaded": 0,
            "failed": 0,
            "skipped": 0,
            "failed_files": [],
            "uploaded_files": []
        }

        # 分批上传
        for i in range(0, len(files_to_upload), batch_size):
            batch = files_to_upload[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(files_to_upload) + batch_size - 1)//batch_size}")

            batch_stats = self._upload_batch(batch)
            stats["uploaded"] += batch_stats["uploaded"]
            stats["failed"] += batch_stats["failed"]
            stats["skipped"] += batch_stats["skipped"]
            stats["failed_files"].extend(batch_stats["failed_files"])
            stats["uploaded_files"].extend(batch_stats["uploaded_files"])

        return stats

    def _upload_batch(self, file_batch: List[tuple]) -> Dict[str, Any]:
        """
        批量上传文件

        Args:
            file_batch: 文件批次列表，每个元素为 (file_path, maven_path) 元组

        Returns:
            批次上传结果
        """
        stats = {
            "uploaded": 0,
            "failed": 0,
            "skipped": 0,
            "failed_files": [],
            "uploaded_files": []
        }

        with tqdm(total=len(file_batch), desc="Uploading to Nexus") as pbar:
            for file_path, maven_path in file_batch:
                try:
                    # 检查文件是否已存在于 Nexus
                    if self._check_file_exists(maven_path):
                        logger.debug(f"File already exists in Nexus, skipping: {maven_path}")
                        stats["skipped"] += 1
                        pbar.update(1)
                        continue

                    # 上传文件
                    result = self.upload_file(file_path, maven_path)

                    if result["success"]:
                        stats["uploaded"] += 1
                        stats["uploaded_files"].append(result["maven_path"])
                    else:
                        stats["failed"] += 1
                        stats["failed_files"].append({
                            "file_path": result["file_path"],
                            "maven_path": result["maven_path"],
                            "error": result.get("error", f"HTTP {result.get('status_code', 'Unknown')}")
                        })

                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    stats["failed"] += 1
                    stats["failed_files"].append({
                        "file_path": str(file_path),
                        "maven_path": maven_path,
                        "error": str(e)
                    })

                pbar.update(1)

        return stats

    def _check_file_exists(self, maven_path: str) -> bool:
        """
        检查文件是否已存在于 Nexus

        Args:
            maven_path: Maven 仓库路径

        Returns:
            文件是否存在
        """
        try:
            # 从路径中解析出版本号
            parts = maven_path.split('/')
            if len(parts) < 2:
                return False

            version = parts[-2]
            target_repository = self.determine_repository(version)

            # 构建 Nexus 搜索 URL
            search_url = f"{self.nexus_url}/service/rest/v1/search/assets"

            params = {
                "repository": target_repository,
                "name": Path(maven_path).name
            }

            response = self.session.get(search_url, params=params)

            if response.status_code == 200:
                assets = response.json().get('items', [])
                # 检查是否有匹配路径的资源
                for asset in assets:
                    if maven_path in asset.get('path', ''):
                        return True

            return False

        except Exception as e:
            logger.warning(f"Failed to check if file exists in Nexus: {maven_path} - {e}")
            return False  # 出错时假设文件不存在，尝试上传

    def test_connection(self) -> bool:
        """
        测试与 Nexus 的连接

        Returns:
            连接是否成功
        """
        try:
            # 获取仓库列表作为连接测试
            repositories_url = f"{self.nexus_url}/service/rest/v1/repositories"
            response = self.session.get(repositories_url)

            if response.status_code == 200:
                repositories = response.json()
                repo_exists = any(repo.get('name') == self.repository for repo in repositories)

                if repo_exists:
                    logger.info(f"Successfully connected to Nexus, repository '{self.repository}' exists")
                else:
                    logger.warning(f"Repository '{self.repository}' not found in Nexus, but will auto-detect snapshot/releases repos")

                # 检测 snapshot 和 releases 仓库
                self._detect_and_log_repositories()

                return True
            else:
                logger.error(f"Failed to connect to Nexus: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error connecting to Nexus: {e}")
            return False

    def _detect_and_log_repositories(self) -> None:
        """
        检测并记录仓库信息
        """
        try:
            repositories = self._get_all_repositories()
            maven_repos = [repo for repo in repositories if repo.get('format') == 'maven2']

            logger.info(f"Found {len(maven_repos)} Maven 2 repositories:")
            for repo in maven_repos:
                repo_name = repo.get('name', '')
                logger.info(f"  - {repo_name}")

            # 检测 snapshot 和 releases 仓库
            snapshot_repo = self._find_snapshot_repository()
            releases_repo = self._find_releases_repository()

            if snapshot_repo:
                logger.info(f"Detected snapshot repository: {snapshot_repo}")
            else:
                logger.warning("No snapshot repository detected - SNAPSHOT versions will be uploaded to default repository")

            if releases_repo:
                logger.info(f"Detected releases repository: {releases_repo}")
            else:
                logger.warning("No releases repository detected - release versions will be uploaded to default repository")

        except Exception as e:
            logger.error(f"Error detecting repositories: {e}")

    def get_repository_mapping(self) -> Dict[str, str]:
        """
        获取仓库映射信息

        Returns:
            仓库映射字典
        """
        snapshot_repo = self._find_snapshot_repository()
        releases_repo = self._find_releases_repository()

        return {
            "snapshot": snapshot_repo or self.repository,
            "releases": releases_repo or self.repository,
            "default": self.repository
        }

    def get_repository_info(self) -> Optional[Dict[str, Any]]:
        """
        获取所有 Maven 仓库信息

        Returns:
            仓库信息字典或 None
        """
        try:
            repositories_url = f"{self.nexus_url}/service/rest/v1/repositories"
            response = self.session.get(repositories_url)

            if response.status_code == 200:
                repositories = response.json()

                # 筛选出 Maven 仓库
                maven_repos = {}
                for repo in repositories:
                    if repo.get('format') == 'maven2':
                        repo_name = repo.get('name')
                        maven_repos[repo_name] = {
                            'name': repo_name,
                            'format': repo.get('format'),
                            'type': repo.get('type'),
                            'url': f"{self.nexus_url}/repository/{repo_name}",
                            'size': repo.get('assets', {}).get('totalSize', 0),
                            'count': repo.get('assets', {}).get('assetCount', 0)
                        }

                return maven_repos if maven_repos else None

            return None

        except Exception as e:
            logger.error(f"Error getting repository info: {e}")
            return None