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

    def __init__(self, token: str, team_id: int, maven_repositories: Optional[Dict[str, Any]] = None, pagination_config: Optional[PaginationConfig] = None, max_workers: int = 8, requests_per_second: int = 20):
        """
        初始化 CODING 客户端

        Args:
            token: CODING API Token
            team_id: 团队 ID
            maven_repositories: Maven 仓库认证配置
            pagination_config: 分页配置
            max_workers: 最大并发线程数
            requests_per_second: 每秒请求数限制
        """
        self.token = token
        self.team_id = team_id
        self.maven_repositories = maven_repositories or {}
        self.pagination_config = pagination_config
        self.max_workers = max_workers
        self.base_url = "https://e.coding.net/open-api/"

        # 速率限制配置 (默认20 req/s，比CODING限制的30 req/s更保守)
        self.requests_per_second = requests_per_second
        self.rate_limiter = threading.Semaphore(requests_per_second)
        self.last_request_time = 0

        # 速率限制统计
        self.request_count = 0
        self.rate_limit_hits = 0
        self.last_stats_time = time.time()

        logger.info(f"CodingClient initialized with rate limit: {requests_per_second} req/s")

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

        # 更新请求统计
        self.request_count += 1
        current_time = time.time()

        # 每100个请求或每分钟报告一次统计
        if self.request_count % 100 == 0 or current_time - self.last_stats_time > 60:
            logger.info(f"API Stats: {self.request_count} requests, {self.rate_limit_hits} rate limit hits, "
                       f"current rate: {self.requests_per_second} req/s")
            self.last_stats_time = current_time

        # 计算距离上次请求的时间
        time_since_last = current_time - self.last_request_time

        # 根据配置的速率限制计算最小间隔
        min_interval = 1.0 / self.requests_per_second

        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            time.sleep(sleep_time)

        self.last_request_time = current_time

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
                    # 如果遇到请求限制，进行智能重试
                    self.rate_limit_hits += 1
                    max_retries = 3
                    for retry in range(max_retries):
                        # 指数退避 + 随机抖动
                        base_wait = 2 ** retry  # 1, 2, 4 秒
                        jitter = random.uniform(0.5, 1.5)  # 随机抖动
                        wait_time = base_wait * jitter

                        logger.warning(f"Rate limit hit (attempt {retry + 1}/{max_retries}), waiting {wait_time:.1f}s before retry...")
                        time.sleep(wait_time)

                        # 降低速率限制
                        original_rate = self.requests_per_second
                        self.requests_per_second = max(5, original_rate // 2)  # 最低5 req/s
                        self.rate_limiter = threading.Semaphore(self.requests_per_second)
                        logger.info(f"Temporarily reduced rate limit to {self.requests_per_second} req/s")

                        # 重试请求
                        try:
                            response = self.session.post(url, params=params, json=data, timeout=30)
                            response.raise_for_status()
                            result = response.json()

                            # 检查重试后是否还有错误
                            if 'Response' in result and 'Error' in result['Response']:
                                retry_error = result['Response']['Error']
                                if retry_error.get('Code') == 'RequestLimitExceeded':
                                    if retry < max_retries - 1:
                                        continue  # 继续重试
                                    else:
                                        raise requests.RequestException(f"API Error: {retry_error.get('Code')} - {retry_error.get('Message', 'Unknown error')} (max retries exceeded)")

                            # 重试成功，恢复原始速率限制
                            self.requests_per_second = original_rate
                            self.rate_limiter = threading.Semaphore(self.requests_per_second)
                            logger.info(f"Restored rate limit to {self.requests_per_second} req/s after successful retry")
                            break

                        except requests.RequestException as retry_exception:
                            if retry < max_retries - 1:
                                logger.warning(f"Retry {retry + 1} failed: {retry_exception}")
                                continue
                            else:
                                raise requests.RequestException(f"API Error: {retry_exception} (max retries exceeded)")
                        finally:
                            # 无论重试是否成功，都确保在一段时间后恢复速率限制
                            def restore_rate():
                                time.sleep(30)  # 30秒后恢复
                                self.requests_per_second = original_rate
                                self.rate_limiter = threading.Semaphore(self.requests_per_second)
                                logger.info(f"Rate limit restored to {self.requests_per_second} req/s")

                            threading.Thread(target=restore_rate, daemon=True).start()
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
            # 使用配置的分页参数，传递 None 让方法内部使用配置
            versions = self.get_maven_versions(project_id, repository_name, filter_config)
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
        # 根据当前速率限制动态调整批量大小
        batch_size = min(20, max(5, self.requests_per_second // 2))  # 5-20之间，取决于速率限制
        total_batches = (len(versions) + batch_size - 1) // batch_size

        logger.info(f"Processing {len(versions)} versions in {total_batches} batches of {batch_size} (rate limit: {self.requests_per_second} req/s)")

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

        # 根据速率限制动态调整并发数，避免过多并发请求
        max_concurrent = min(self.max_workers, len(tasks), max(2, self.requests_per_second // 3))
        logger.debug(f"Using {max_concurrent} concurrent workers for {len(tasks)} tasks (rate limit: {self.requests_per_second} req/s)")

        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
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

    def get_maven_versions(self, project_id: int, repository_name: str, filter_config: Optional[MavenFilterConfig] = None, max_pages: int = None) -> List[Dict[str, Any]]:
        """
        获取 Maven 制品版本列表

        Args:
            project_id: 项目 ID
            repository_name: 仓库名称
            filter_config: Maven 过滤配置
            max_pages: 最大页数限制，防止无限循环，默认使用配置文件中的值

        Returns:
            Maven 制品版本列表
        """
        logger.info(f"Fetching Maven versions for project {project_id}, repository {repository_name}")

        # 使用配置文件中的最大页数限制，如果没有配置则使用更大的默认值
        if max_pages is None:
            max_pages = self.pagination_config.max_pages if self.pagination_config else 1000

        logger.info(f"Using max_pages limit: {max_pages}")

        try:
            # 直接使用 DescribeTeamArtifacts API 获取包和版本信息，获取所有页
            all_packages = []
            page_number = 1
            page_size = self.pagination_config.page_size if self.pagination_config else 100

            consecutive_empty_pages = 0  # 连续空页面计数器，防止某些情况下API异常
            max_consecutive_empty = 3    # 最大连续空页面数

            while page_number <= max_pages:
                logger.debug(f"Fetching page {page_number}/{max_pages} with page_size {page_size}")

                packages = self.get_maven_packages(project_id, repository_name, filter_config, page_number, page_size)

                if not packages:
                    consecutive_empty_pages += 1
                    logger.info(f"No packages found on page {page_number}")

                    # 如果连续多个页面都为空，认为真的没有更多数据了
                    if consecutive_empty_pages >= max_consecutive_empty:
                        logger.info(f"No packages found for {max_consecutive_empty} consecutive pages, stopping pagination")
                        break

                    # 继续尝试下一页，可能是API异常
                    page_number += 1
                    continue
                else:
                    consecutive_empty_pages = 0  # 重置空页面计数器

                all_packages.extend(packages)
                logger.info(f"Retrieved {len(packages)} packages from page {page_number}, total so far: {len(all_packages)}")

                # 更健壮的分页终止条件：
                # 1. 如果返回的包数量小于页面大小，可能是最后一页，但需要再验证一次
                # 2. 如果返回的包数量等于页面大小，继续获取下一页
                if len(packages) < page_size:
                    logger.info(f"Got {len(packages)} packages < page_size {page_size}, checking if this is really the last page")

                    # 再获取一页来确认是否真的到最后一页了
                    # 这处理了API正好返回page_size整数倍数据的情况
                    next_page_packages = self.get_maven_packages(project_id, repository_name, filter_config, page_number + 1, page_size)
                    if not next_page_packages:
                        logger.info(f"Confirmed: page {page_number} is the last page")
                        break
                    else:
                        logger.info(f"There are more packages after page {page_number}, continuing pagination")
                        # 如果下一页有数据，说明当前页不是最后一页，继续处理
                        all_packages.extend(next_page_packages)
                        logger.info(f"Retrieved {len(next_page_packages)} packages from page {page_number + 1}, total so far: {len(all_packages)}")
                        page_number += 2  # 跳过已经处理的下一页
                        continue

                page_number += 1

            # 检查是否因为达到最大页数限制而停止
            if page_number > max_pages:
                logger.warning(f"⚠️  Reached maximum page limit ({max_pages}), some packages may be missing!")
                logger.warning(f"Consider increasing 'pagination.max_pages' in config.yaml if you expect more data")

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

            logger.info(f"[OK] Found {len(versions)} total versions across all packages in repository {repository_name}")
            logger.info(f"   Retrieved from {page_number-1} pages")
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
                logger.debug(f"[INFO] Found {len(artifacts)} artifacts for {package_name}:{package_version}")
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

    def download_artifact(self, project_id: int, repository_name: str, file_path: str, output_path: str, download_url: str) -> bool:
        """
        下载制品文件

        Args:
            project_id: 项目 ID
            repository_name: 仓库名称
            file_path: 文件路径
            output_path: 输出路径
            download_url: 下载 URL（必须由 API 提供）

        Returns:
            下载是否成功
        """
        logger.info(f"Downloading artifact: {file_path}")

        # 使用 project_id 来获取项目名称（用于回退）
        project_name = self.get_project_name_by_id(project_id)

        # 只使用 API 提供的下载 URL
        if not download_url:
            logger.error("No download URL provided by API")
            return False

        target_url = download_url

        try:
            logger.debug(f"Downloading from: {target_url}")

            # 为 Maven 仓库下载添加基本认证
            auth = None
            project_name = self.get_project_name_by_id(project_id)

            # 检查是否为 Maven 仓库 URL（包含 .pkg.coding.net）
            if ".pkg.coding.net" in target_url:
                # 从 URL 路径中提取项目名称
                # URL 格式: https://domain.pkg.coding.net/repository/project-name/repo-name/...
                import re
                url_pattern = r'https://[^/]+/repository/([^/]+)/([^/]+)/'
                match = re.search(url_pattern, target_url)

                if match:
                    url_project_name = match.group(1)  # URL路径中的项目名称
                    url_repo_name = match.group(2)     # URL路径中的仓库名称
                    # 优先使用URL中的项目名称来匹配认证信息
                    if url_project_name and url_project_name in self.maven_repositories:
                        project_repos = self.maven_repositories[url_project_name]
                        # 处理嵌套配置对象
                        if hasattr(project_repos, url_repo_name):
                            repo_config = getattr(project_repos, url_repo_name)
                            auth = (repo_config.username, repo_config.password)
                            logger.info(f"Using auth for URL project: {url_project_name}, repo: {url_repo_name}")
                        else:
                            logger.warning(f"No auth found for repository: {url_repo_name} in URL project: {url_project_name}")
                    else:
                        logger.warning(f"No auth configuration found for URL project: {url_project_name}")
                        # 回退到使用 project_id 对应的项目名称
                        if project_name and project_name in self.maven_repositories:
                            project_repos = self.maven_repositories[project_name]
                            if hasattr(project_repos, repository_name):
                                repo_config = getattr(project_repos, repository_name)
                                auth = (repo_config.username, repo_config.password)
                                logger.info(f"Using fallback auth for project: {project_name}, repo: {repository_name}")
                            else:
                                logger.warning(f"No auth found for repository: {repository_name} in fallback project: {project_name}")
                        else:
                            logger.warning(f"No auth configuration found for fallback project: {project_name}")
                else:
                    # 如果无法从URL提取，使用原有逻辑
                    logger.warning(f"Could not extract project/repo from URL: {target_url}")
                    if project_name and project_name in self.maven_repositories:
                        project_repos = self.maven_repositories[project_name]
                        if hasattr(project_repos, repository_name):
                            repo_config = getattr(project_repos, repository_name)
                            auth = (repo_config.username, repo_config.password)
                            logger.info(f"Using basic auth for project: {project_name}, repo: {repository_name}")
                            logger.info(f"Auth username: {repo_config.username}")
                        else:
                            logger.warning(f"No auth found for repository: {repository_name} in project: {project_name}")
                    else:
                        logger.warning(f"No auth configuration found for project: {project_name}")
            else:
                logger.debug(f"Not a Maven repository URL, skipping auth: {target_url}")

            logger.info(f"Final auth: {'None' if auth is None else f'username={auth[0]}'}")
            response = self.session.get(target_url, stream=True, auth=auth)
            response.raise_for_status()

            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Successfully downloaded {file_path} to {output_path}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download {file_path}: {e}")
            return False