"""
数据模型定义
"""

from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime


class CodingProject(BaseModel):
    """CODING 项目模型"""
    id: int
    created_at: Union[int, datetime]
    updated_at: Union[int, datetime]
    status: int
    type: int
    max_member: int
    name: str
    display_name: str
    description: str
    icon: str
    team_owner_id: int
    user_owner_id: int
    start_date: int
    end_date: int
    team_id: int
    is_demo: bool
    archived: bool
    program_ids: List[int] = []


class DescribeProjectsResponse(BaseModel):
    """获取项目列表响应模型"""
    page_number: int = Field(alias="PageNumber")
    page_size: int = Field(alias="PageSize")
    total_count: int = Field(alias="TotalCount")
    project_list: List[CodingProject] = Field(alias="ProjectList")


class ApiResponse(BaseModel):
    """API 响应基础模型"""
    response: Dict[str, Any] = Field(alias="Response")


class MavenArtifact(BaseModel):
    """Maven 制品模型"""
    group_id: str
    artifact_id: str
    version: str
    packaging: str = "jar"
    file_path: str
    repository: Optional[str] = None  # 所属的仓库
    size: Optional[int] = None
    sha1: Optional[str] = None
    md5: Optional[str] = None
    download_url: Optional[str] = None


class MavenRepositoryConfig(BaseModel):
    """Maven 仓库认证配置模型"""
    username: str
    password: str


class ProjectRepositoryConfig(BaseModel):
    """项目级 Maven 仓库配置模型"""
    releases: Optional[MavenRepositoryConfig] = None
    snapshots: Optional[MavenRepositoryConfig] = None


class MavenFilterConfig(BaseModel):
    """Maven 过滤配置模型"""
    enabled: bool = False
    patterns: List[str] = []


class PaginationConfig(BaseModel):
    """分页配置模型"""
    page_size: int = 100
    max_pages: int = 50


class PerformanceConfig(BaseModel):
    """性能优化配置模型"""
    max_workers: int = 12
    batch_size: int = 50


class MigrationConfig(BaseModel):
    """迁移配置模型"""
    coding_token: str
    coding_team_id: int
    nexus_url: str
    nexus_username: str
    nexus_password: str
    nexus_repository: str
    nexus_snapshot_repository: Optional[str] = None
    nexus_releases_repository: Optional[str] = None
    project_names: List[str] = []
    download_path: str = "./downloads"
    batch_size: int = 100
    parallel_downloads: int = 5
    maven_filter: MavenFilterConfig = MavenFilterConfig()
    pagination: PaginationConfig = PaginationConfig()
    performance: PerformanceConfig = PerformanceConfig()
    maven_repositories: Dict[str, Union[MavenRepositoryConfig, ProjectRepositoryConfig]] = {}