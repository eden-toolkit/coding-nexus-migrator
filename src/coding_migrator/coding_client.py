"""
CODING API 客户端
"""

import requests
import logging
import time
import random
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin
from .models import CodingProject, DescribeProjectsResponse, ApiResponse, MavenArtifact, MavenFilterConfig, PaginationConfig


logger = logging.getLogger(__name__)


class CodingClient:
    """CODING API 客户端"""

    def __init__(self, token: str, team_id: int, maven_repositories: Optional[Dict[str, Any]] = None, pagination_config: Optional[PaginationConfig] = None, max_workers: int = 8):
        """
        初始化 CODING 客户端

        Args:
            token: CODING API Token
            team_id: 团队 ID
            maven_repositories: Maven 仓库认证配置
            pagination_config: 分页配置
            max_workers: 最大并发线程数
        """
        self.token = token
        self.team_id = team_id
        self.maven_repositories = maven_repositories or {}
        self.pagination_config = pagination_config
        self.max_workers = max_workers
        self.base_url = "https://e.coding.net/open-api/"
        self.maven_base_url = "https://puyifund-maven.pkg.coding.net"

        # 速率限制控制 (30 req/s 限制，我们使用 25 req/s 留出安全边际)
        self.rate_limiter = threading.Semaphore(25)
        self.last_request_time = 0

        # 创建会话，配置连接池
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20,
            pool_maxsize=20,
            max_retries=3
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Connection': 'keep-alive'
        })

    def _rate_limit(self):
        """智能速率限制控制"""
        # 获取信号量
        self.rate_limiter.acquire()

        # 计算距离上次请求的时间
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        # 确保每秒不超过 25 个请求（40ms 间隔）
        min_interval = 0.04  # 1/25 秒

        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            time.sleep(sleep_time)

        self.last_request_time = time.time()

        # 在一个单独的线程中延迟释放信号量
        def release_semaphore():
            time.sleep(0.05)  # 50ms 后释放
            self.rate_limiter.release()

        threading.Thread(target=release_semaphore, daemon=True).start()

    def _make_request(self, action: str, params: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        发起 API 请求

        Args:
            action: API 动作名称
            params: URL 参数
            data: 请求体数据

        Returns:
            API 响应数据

        Raises:
            requests.RequestException: 请求失败
        """
        # 应用速率限制
        self._rate_limit()

        url = urljoin(self.base_url, f"?Action={action}")

        try:
            response = self.session.post(url, params=params, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()

            # 检查响应中是否有错误
            if 'Response' in result and 'Error' in result['Response']:
                error = result['Response']['Error']
                if error.get('Code') == 'RequestLimitExceeded':
                    # 如果遇到请求限制，等待后重试
                    wait_time = random.uniform(1.0, 2.0)
                    logger.warning(f"Rate limit hit, waiting {wait_time:.1f}s before retry...")
                    time.sleep(wait_time)

                    # 重试一次
                    response = self.session.post(url, params=params, json=data, timeout=30)
                    response.raise_for_status()
                    result = response.json()

                    # 如果重试后仍然有限制错误，抛出异常
                    if 'Response' in result and 'Error' in result['Response']:
                        retry_error = result['Response']['Error']
                        if retry_error.get('Code') == 'RequestLimitExceeded':
                            raise requests.RequestException(f"API Error: {retry_error.get('Code')} - {retry_error.get('Message', 'Unknown error')}")
                else:
                    raise requests.RequestException(f"API Error: {error.get('Code', 'Unknown')} - {error.get('Message', 'Unknown error')}")

            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise

    def get_projects(self, page_number: int = 1, page_size: int = 100) -> List[CodingProject]:
        """
        获取项目列表

        Args:
            page_number: 页码
            page_size: 每页数量

        Returns:
            项目列表
        """
        logger.info(f"Fetching projects page {page_number} with size {page_size}")

        data = {
            "PageNumber": str(page_number),
            "PageSize": str(page_size)
        }

        response = self._make_request("DescribeCodingProjects", data=data)

        try:
            # 直接解析响应数据，避免复杂的模型验证
            response_data = response.get('Response', {})
            data_section = response_data.get('Data', {})
            project_list = data_section.get('ProjectList', [])

            projects = []
            for project_data in project_list:
                # 手动创建项目对象，使用正确的大写字段名格式
                project = CodingProject(
                    id=project_data.get('Id', 0),
                    created_at=project_data.get('CreatedAt', 0),
                    updated_at=project_data.get('UpdatedAt', 0),
                    status=project_data.get('Status', 0),
                    type=project_data.get('Type', 0),
                    max_member=project_data.get('MaxMember', 0),
                    name=project_data.get('Name', ''),
                    display_name=project_data.get('DisplayName', ''),
                    description=project_data.get('Description', ''),
                    icon=project_data.get('Icon', ''),
                    team_owner_id=project_data.get('TeamOwnerId', 0),
                    user_owner_id=project_data.get('UserOwnerId', 0),
                    start_date=project_data.get('StartDate', 0),
                    end_date=project_data.get('EndDate', 0),
                    team_id=project_data.get('TeamId', 0),
                    is_demo=project_data.get('IsDemo', False),
                    archived=project_data.get('Archived', False),
                    program_ids=project_data.get('ProgramIds', [])
                )
                projects.append(project)

            return projects

        except Exception as e:
            logger.error(f"Failed to parse projects response: {e}")
            logger.debug(f"Response data: {response}")
            return []

    def get_all_projects(self) -> List[CodingProject]:
        """
        获取所有项目

        Returns:
            所有项目列表
        """
        all_projects = []
        page_number = 1
        page_size = 100

        while True:
            projects = self.get_projects(page_number, page_size)
            all_projects.extend(projects)

            if len(projects) < page_size:
                break

            page_number += 1

        logger.info(f"Retrieved {len(all_projects)} projects")
        return all_projects

    def get_project_by_name(self, project_name: str) -> Optional[CodingProject]:
        """
        根据项目名称获取项目

        Args:
            project_name: 项目名称

        Returns:
            项目信息或 None
        """
        projects = self.get_all_projects()

        for project in projects:
            if project.name == project_name:
                return project

        return None

    def get_project_name_by_id(self, project_id: int) -> str:
        """
        根据项目ID获取项目名称

        Args:
            project_id: 项目 ID

        Returns:
            项目名称
        """
        # 缓存项目名称映射
        if not hasattr(self, '_project_name_cache'):
            self._project_name_cache = {}

        # 先检查缓存
        if project_id in self._project_name_cache:
            return self._project_name_cache[project_id]

        try:
            # 获取所有项目并查找匹配的项目ID
            if not hasattr(self, '_all_projects_cache'):
                self._all_projects_cache = self.get_all_projects()

            for project in self._all_projects_cache:
                if project.id == project_id:
                    project_name = project.name
                    # 缓存结果
                    self._project_name_cache[project_id] = project_name
                    return project_name

            # 如果没找到，返回ID字符串
            logger.debug(f"Project with ID {project_id} not found")
            return str(project_id)
        except Exception as e:
            logger.debug(f"Failed to get project name for ID {project_id}: {e}")
            return str(project_id)

    def get_artifact_repositories(self, project_id: int) -> List[Dict[str, Any]]:
        """
        获取项目的制品仓库列表

        Args:
            project_id: 项目 ID

        Returns:
            制品仓库列表
        """
        logger.info(f"Fetching artifact repositories for project {project_id}")

        try:
            data = {
                "ProjectId": project_id,
                "PageNumber": 1,
                "PageSize": 100
            }

            response = self._make_request("DescribeArtifactRepositoryList", data=data)
            all_repos = response.get('Response', {}).get('Data', {}).get('InstanceSet', [])

            logger.info(f"Found {len(all_repos)} repositories for project {project_id}")
            for repo in all_repos:
                logger.info(f"Repository: {repo.get('Name')} (ID: {repo.get('Id')}, Type: {repo.get('Type')})")

            return all_repos

        except Exception as e:
            logger.error(f"Failed to get artifact repositories: {e}")
            raise

    def get_team_artifacts(self, project_id: int) -> List[Dict[str, Any]]:
        """
        获取团队级别的制品（备用方法）

        Args:
            project_id: 项目 ID

        Returns:
            制品列表
        """
        try:
            data = {
                "ProjectId": project_id,
                "PageNumber": 1,
                "PageSize": 100
            }

            response = self._make_request("DescribeTeamArtifacts", data=data)
            artifacts = response.get('Response', {}).get('InstanceSet', [])

            if artifacts:
                logger.info(f"Found {len(artifacts)} team-level artifacts, assuming standard Maven repositories")
                return [{"Name": "releases", "Type": 3}, {"Name": "snapshots", "Type": 3}]

            return []

        except Exception as e:
            logger.debug(f"Team artifacts API failed: {e}")
            return []

    def get_maven_artifacts(self, project_id: int, repository_name: str, filter_config: Optional[MavenFilterConfig] = None) -> List[MavenArtifact]:
        """
        获取 Maven 制品列表（并发优化版本）

        Args:
            project_id: 项目 ID
            repository_name: 仓库名称
            filter_config: Maven 过滤配置

        Returns:
            Maven 制品列表
        """
        logger.info(f"Fetching Maven artifacts for project {project_id}, repository {repository_name}")

        # 首先获取 Maven 制品版本列表
        try:
            # 使用配置的分页参数
            max_pages = self.pagination_config.max_pages if self.pagination_config else 50
            versions = self.get_maven_versions(project_id, repository_name, filter_config, max_pages)
            logger.info(f"Found {len(versions)} Maven package versions")

            # 获取项目名称用于文件列表查询
            project_name = self.get_project_name_by_id(project_id)

            # 并发获取所有版本的文件列表
            artifacts = self._get_artifacts_concurrent(project_id, project_name, repository_name, versions)

            return artifacts

        except Exception as e:
            logger.warning(f"Failed to get Maven artifacts from repository {repository_name}: {e}")
            return []

    def _get_artifacts_concurrent(self, project_id: int, project_name: str, repository_name: str, versions: List[Dict[str, Any]]) -> List[MavenArtifact]:
        """
        并发获取所有版本的制品文件列表

        Args:
            project_id: 项目 ID
            project_name: 项目名称
            repository_name: 仓库名称
            versions: 版本信息列表

        Returns:
            所有制品列表
        """
        all_artifacts = []

        # 分批处理，避免同时发送过多请求
        batch_size = 50  # 每批处理 50 个版本
        total_batches = (len(versions) + batch_size - 1) // batch_size

        logger.info(f"Processing {len(versions)} versions in {total_batches} batches of {batch_size}")

        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(versions))
            batch_versions = versions[start_idx:end_idx]

            logger.info(f"Processing batch {batch_num + 1}/{total_batches} ({len(batch_versions)} versions)")

            # 创建任务列表
            tasks = []
            for version_info in batch_versions:
                package_name = version_info.get('Package', '')
                package_version = version_info.get('PackageVersion', '')

                if package_name and package_version:
                    task = {
                        'package_name': package_name,
                        'package_version': package_version
                    }
                    tasks.append(task)

            # 并发执行任务
            batch_artifacts = self._execute_batch_tasks(project_id, project_name, repository_name, tasks)
            all_artifacts.extend(batch_artifacts)

            logger.info(f"Batch {batch_num + 1} completed, found {len(batch_artifacts)} artifacts")

        return all_artifacts

    def _execute_batch_tasks(self, project_id: int, project_name: str, repository_name: str, tasks: List[Dict[str, str]]) -> List[MavenArtifact]:
        """
        执行一批并发任务

        Args:
            project_id: 项目 ID
            project_name: 项目名称
            repository_name: 仓库名称
            tasks: 任务列表

        Returns:
            制品列表
        """
        artifacts = []

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as executor:
            # 提交所有任务
            future_to_task = {}
            for task in tasks:
                future = executor.submit(
                    self.get_maven_version_files,
                    project_id, project_name, repository_name,
                    task['package_name'], task['package_version']
                )
                future_to_task[future] = task

            # 收集结果
            completed = 0
            for future in as_completed(future_to_task):
                try:
                    task_artifacts = future.result(timeout=60)  # 60秒超时
                    artifacts.extend(task_artifacts)
                    completed += 1

                    if completed % 10 == 0 or completed == len(tasks):
                        logger.info(f"Completed {completed}/{len(tasks)} tasks in current batch")

                except Exception as e:
                    task = future_to_task[future]
                    logger.error(f"Failed to get artifacts for {task['package_name']}:{task['package_version']}: {e}")

        return artifacts

    def get_maven_packages(self, project_id: int, repository_name: str, filter_config: Optional[MavenFilterConfig] = None, page_number: int = 1, page_size: int = 100) -> List[Dict[str, Any]]:
        """
        获取 Maven 制品包列表

        Args:
            project_id: 项目 ID
            repository_name: 仓库名称
            filter_config: Maven 过滤配置
            page_number: 页码
            page_size: 每页数量

        Returns:
            Maven 制品包列表
        """
        logger.info(f"Fetching Maven packages for project {project_id}, repository {repository_name}")

        try:
            # 使用 DescribeTeamArtifacts API 获取 Maven 制品
            # 使用项目的实际名称而不是ID
            project_name = self.get_project_name_by_id(project_id)

            # 构建基本请求规则
            rule = {
                "ArtifactType": [3],  # Maven 类型
                "ProjectName": [project_name],
                "Repository": [repository_name]
            }

            # 添加包过滤规则
            if filter_config and filter_config.enabled and filter_config.patterns:
                package_filters = []
                for pattern in filter_config.patterns:
                    package_filters.append({
                        "Algorithm": "REGEX",
                        "Value": pattern
                    })
                rule["Package"] = package_filters
                logger.info(f"Applying Maven package filters: {filter_config.patterns}")

            data = {
                "PageNumber": page_number,
                "PageSize": page_size,
                "Rule": rule
            }

            response = self._make_request("DescribeTeamArtifacts", data=data)
            packages = response.get('Response', {}).get('Data', {}).get('InstanceSet', [])

            logger.info(f"Found {len(packages)} Maven packages in repository {repository_name}")
            logger.debug(f"API request data: {data}")
            logger.debug(f"API response: {response}")
            return packages

        except Exception as e:
            logger.warning(f"Failed to get Maven packages: {e}")
            return []

    def get_maven_versions(self, project_id: int, repository_name: str, filter_config: Optional[MavenFilterConfig] = None, max_pages: int = 10) -> List[Dict[str, Any]]:
        """
        获取 Maven 制品版本列表

        Args:
            project_id: 项目 ID
            repository_name: 仓库名称
            filter_config: Maven 过滤配置
            max_pages: 最大页数限制，防止无限循环

        Returns:
            Maven 制品版本列表
        """
        logger.info(f"Fetching Maven versions for project {project_id}, repository {repository_name}")

        try:
            # 直接使用 DescribeTeamArtifacts API 获取包和版本信息，获取所有页
            all_packages = []
            page_number = 1
            page_size = 100

            while page_number <= max_pages:
                packages = self.get_maven_packages(project_id, repository_name, filter_config, page_number, page_size)
                if not packages:
                    logger.info(f"No more packages found after page {page_number-1}")
                    break

                all_packages.extend(packages)
                logger.info(f"Retrieved {len(packages)} packages from page {page_number}")

                # 如果返回的包数量小于页面大小，说明已经是最后一页
                if len(packages) < page_size:
                    logger.info(f"Reached last page (got {len(packages)} packages < page_size {page_size})")
                    break

                page_number += 1

            # 检查是否因为达到最大页数限制而停止
            if page_number > max_pages:
                logger.warning(f"Reached maximum page limit ({max_pages}), some packages may be missing")

            packages = all_packages

            if not packages:
                logger.warning(f"No Maven packages found in repository {repository_name}")
                return []

            # 从包信息中提取版本信息
            versions = []
            for package in packages:
                version_info = {
                    "Package": package.get('Package', ''),
                    "PackageVersion": package.get('PackageVersion', ''),
                    "VersionId": package.get('VersionId', ''),
                    "ProjectId": package.get('ProjectId', project_id),
                    "Repository": package.get('Repository', repository_name),
                    "ReleaseStatus": package.get('ReleaseStatus', 1),
                    "CreatedAt": package.get('CreatedAt', 0)
                }
                versions.append(version_info)

            logger.info(f"Found {len(versions)} total versions across all packages in repository {repository_name}")
            return versions

        except Exception as e:
            logger.warning(f"Failed to get Maven versions: {e}")
            return []

    def get_maven_version_files(self, project_id: int, project_name: str, repository_name: str,
                               package_name: str, package_version: str) -> List[MavenArtifact]:
        """
        获取 Maven 制品版本的文件列表

        Args:
            project_id: 项目 ID
            project_name: 项目名称
            repository_name: 仓库名称
            package_name: 包名
            package_version: 版本号

        Returns:
            Maven 制品列表
        """
        logger.debug(f"Fetching files for {package_name}:{package_version}")

        try:
            # 使用正确的 DescribeArtifactRepositoryFileList API
            data = {
                "Project": project_name,
                "Repository": repository_name,
                "ContinuationToken": "",
                "PageSize": 1000,
                "Artifacts": [
                    {
                        "PackageName": package_name,
                        "VersionName": package_version
                    }
                ]
            }

            logger.debug(f"API request data for file list: {data}")
            response = self._make_request("DescribeArtifactRepositoryFileList", data=data)
            logger.debug(f"File list API response: {response}")

            artifacts = []
            files_data = response.get('Response', {}).get('Data', {}).get('InstanceSet', [])

            for file_data in files_data:
                # 解析文件信息
                download_url = file_data.get('DownloadUrl', '')
                file_path = file_data.get('Path', '')
                file_name = file_path.split('/')[-1] if file_path else ''

                # 只处理主要的Maven文件类型
                if file_name and (file_name.endswith('.jar') or file_name.endswith('.pom') or
                   file_name.endswith('-sources.jar') or file_name.endswith('.war')):

                    # 解析 Maven 坐标
                    artifact = self._parse_maven_package_info(package_name, package_version, file_name, repository_name)
                    if artifact:
                        artifact.file_path = file_path
                        artifact.download_url = download_url
                        artifacts.append(artifact)

            logger.debug(f"Found {len(artifacts)} files for {package_name}:{package_version}")
            if artifacts:
                logger.debug(f"📦 Found {len(artifacts)} artifacts for {package_name}:{package_version}")
                for i, artifact in enumerate(artifacts[:3], 1):  # 显示前3个文件
                    logger.debug(f"  {i}. {artifact.download_url.split('/')[-1]}")
                if len(artifacts) > 3:
                    logger.debug(f"  ... and {len(artifacts) - 3} more files")
            return artifacts

        except Exception as e:
            logger.warning(f"Failed to get Maven version files for {package_name}:{package_version}: {e}")
            return []

    def _parse_maven_package_info(self, package_name: str, version: str, file_name: str, repository_name: str = None) -> Optional[MavenArtifact]:
        """
        解析 Maven 包信息

        Args:
            package_name: 包名
            version: 版本号
            file_name: 文件名

        Returns:
            MavenArtifact 或 None
        """
        try:
            # 解析 groupId 和 artifactId
            # package_name 格式通常是：groupId:artifactId
            if ':' in package_name:
                group_id, artifact_id = package_name.split(':', 1)
            else:
                # 如果没有冒号，假设整个是 artifactId，groupId 设为默认值
                group_id = "unknown"
                artifact_id = package_name

            # 确定打包类型
            if file_name.endswith('.pom'):
                packaging = 'pom'
            elif file_name.endswith('-sources.jar'):
                packaging = 'jar'
            elif file_name.endswith('.jar'):
                packaging = 'jar'
            elif file_name.endswith('.war'):
                packaging = 'war'
            else:
                packaging = 'jar'

            return MavenArtifact(
                group_id=group_id,
                artifact_id=artifact_id,
                version=version,
                packaging=packaging,
                file_path=f"{package_name}/{version}/{file_name}",
                repository=repository_name  # 添加仓库信息
            )

        except Exception as e:
            logger.warning(f"Failed to parse Maven package info from {package_name}:{file_name}: {e}")
            return None

    def _build_maven_file_path(self, package_name: str, package_version: str) -> str:
        """
        构建 Maven 文件路径

        Args:
            package_name: 包名 (groupId:artifactId)
            package_version: 版本号

        Returns:
            Maven 文件路径
        """
        # 解析 groupId 和 artifactId
        if ':' in package_name:
            group_id, artifact_id = package_name.split(':', 1)
        else:
            group_id = "unknown"
            artifact_id = package_name

        # 将 groupId 的点转换为路径分隔符
        group_path = group_id.replace('.', '/')

        # 构建标准 Maven 文件路径
        return f"{group_path}/{artifact_id}/{package_version}/{artifact_id}-{package_version}.jar"

    def _build_download_url(self, project_id: int, repository_name: str, file_path: str) -> str:
        """
        构建 CODING 下载 URL

        Args:
            project_id: 项目 ID
            repository_name: 仓库名称
            file_path: 文件路径

        Returns:
            下载 URL
        """
        # 构建 CODING 标准下载 URL
        return f"https://{self.team_id}.coding.net/p/{project_id}/d/artifacts/{repository_name}/raw/{file_path}"

    def _parse_maven_path(self, file_path: str) -> Optional[MavenArtifact]:
        """
        解析 Maven 文件路径获取坐标信息

        Args:
            file_path: Maven 文件路径

        Returns:
            MavenArtifact 或 None
        """
        # 示例路径: groupId/artifactId/version/artifactId-version.packaging
        parts = file_path.split('/')

        if len(parts) < 4:
            return None

        version = parts[-2]
        filename = parts[-1]

        # 解析文件名
        if filename.endswith('.jar'):
            artifact_id_version = filename[:-4]  # 去掉 .jar
        elif filename.endswith('.pom'):
            artifact_id_version = filename[:-4]  # 去掉 .pom
        elif filename.endswith('-sources.jar'):
            artifact_id_version = filename[:-11]  # 去掉 -sources.jar
        else:
            artifact_id_version = filename

        # 分离 artifact_id 和 version
        if f"-{version}" in artifact_id_version:
            artifact_id = artifact_id_version[:artifact_id_version.rfind(f"-{version}")]
        else:
            artifact_id = artifact_id_version

        group_id = '/'.join(parts[:-3])

        packaging = "jar"
        if filename.endswith('.pom'):
            packaging = "pom"
        elif filename.endswith('-sources.jar'):
            packaging = "jar"

        return MavenArtifact(
            group_id=group_id,
            artifact_id=artifact_id,
            version=version,
            packaging=packaging,
            file_path=file_path,
            repository=None  # 这个方法无法确定仓库，设为None
        )

    def download_artifact(self, project_id: int, repository_name: str, file_path: str, output_path: str, download_url: str = None) -> bool:
        """
        下载制品文件

        Args:
            project_id: 项目 ID
            repository_name: 仓库名称
            file_path: 文件路径
            output_path: 输出路径
            download_url: 下载 URL（可选，优先使用）

        Returns:
            下载是否成功
        """
        logger.info(f"Downloading artifact: {file_path}")

        # 优先使用 API 提供的下载 URL
        if download_url:
            target_url = download_url
        else:
            # 构建 CODING 标准下载 URL
            target_url = f"https://{self.team_id}.coding.net/p/{project_id}/d/artifacts/{repository_name}/raw/{file_path}"

        try:
            logger.debug(f"Downloading from: {target_url}")

            # 为 Maven 仓库下载添加基本认证
            auth = None
            if target_url.startswith(self.maven_base_url):
                # 确定使用哪个仓库的认证信息
                repo_key = None
                if repository_name == "releases":
                    repo_key = "puyifund-platform-releases"
                elif repository_name == "snapshots":
                    repo_key = "puyifund-platform-snapshots"

                if repo_key and repo_key in self.maven_repositories:
                    repo_config = self.maven_repositories[repo_key]
                    auth = (repo_config.username, repo_config.password)
                    logger.debug(f"Using basic auth for repository: {repo_key}")

            response = self.session.get(target_url, stream=True, auth=auth)
            response.raise_for_status()

            # 确保输出目录存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Successfully downloaded {file_path} to {output_path}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download {file_path}: {e}")
            return False