"""
配置管理模块
"""

import os
import yaml
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from .models import MigrationConfig, MavenFilterConfig, MavenRepositoryConfig, PaginationConfig, PerformanceConfig


logger = logging.getLogger(__name__)


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_file: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_file: 配置文件路径，默认为 config.yaml
        """
        self.config_file = Path(config_file) if config_file else Path("config.yaml")

    def load_config(self) -> MigrationConfig:
        """
        加载配置文件

        Returns:
            迁移配置对象

        Raises:
            FileNotFoundError: 配置文件不存在
            yaml.YAMLError: 配置文件格式错误
            ValueError: 配置验证失败
        """
        if not self.config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_file}")

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            # 验证必要配置项
            self._validate_config(config_data)

            # 构建 Maven 过滤配置
            maven_filter_data = config_data['coding'].get('maven_filter', {})
            # 兼容旧格式，支持 package_patterns 字段
            patterns = maven_filter_data.get('patterns') or maven_filter_data.get('package_patterns', [])
            maven_filter = MavenFilterConfig(
                enabled=maven_filter_data.get('enabled', False),
                patterns=patterns
            )

            # 构建分页配置
            pagination_data = config_data['coding'].get('pagination', {})
            pagination = PaginationConfig(
                page_size=pagination_data.get('page_size', 100),
                max_pages=pagination_data.get('max_pages', 50)
            )

            # 构建 Maven 仓库认证配置
            maven_repositories_data = config_data['coding'].get('maven_repositories', {})
            maven_repositories = {}
            for repo_name, repo_config in maven_repositories_data.items():
                maven_repositories[repo_name] = MavenRepositoryConfig(
                    username=repo_config['username'],
                    password=repo_config['password']
                )

            # 构建性能优化配置
            performance_data = config_data['coding'].get('performance', {})
            performance = PerformanceConfig(
                max_workers=performance_data.get('max_workers', 12),
                batch_size=performance_data.get('batch_size', 50)
            )

            # 构建 MigrationConfig 对象
            migration_config = MigrationConfig(
                coding_token=config_data['coding']['token'],
                coding_team_id=config_data['coding']['team_id'],
                nexus_url=config_data['nexus']['url'],
                nexus_username=config_data['nexus']['username'],
                nexus_password=config_data['nexus']['password'],
                nexus_repository=config_data['nexus'].get('release_repo', config_data['nexus'].get('repository', 'maven-releases')),
                nexus_snapshot_repository=config_data['nexus'].get('snapshot_repo'),
                nexus_releases_repository=config_data['nexus'].get('release_repo'),
                project_names=config_data['migration'].get('project_names', []),
                download_path=config_data['migration'].get('download_path', './downloads'),
                batch_size=config_data['migration'].get('batch_size', 100),
                parallel_downloads=config_data['migration'].get('parallel_downloads', 5),
                maven_filter=maven_filter,
                pagination=pagination,
                performance=performance,
                maven_repositories=maven_repositories
            )

            logger.info(f"Configuration loaded from: {self.config_file}")
            return migration_config

        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML configuration: {e}")
            raise
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            raise

    def load_config_with_env(self) -> MigrationConfig:
        """
        加载配置文件并支持环境变量覆盖

        Returns:
            迁移配置对象

        Raises:
            FileNotFoundError: 配置文件不存在
            yaml.YAMLError: 配置文件格式错误
            ValueError: 配置验证失败
        """
        # 先加载基础配置
        config = self.load_config()

        # 使用环境变量覆盖配置
        if os.getenv('CODING_TOKEN'):
            config.coding_token = os.getenv('CODING_TOKEN')
            logger.info("Using CODING_TOKEN from environment variable")

        if os.getenv('CODING_TEAM_ID'):
            try:
                config.coding_team_id = int(os.getenv('CODING_TEAM_ID'))
                logger.info("Using CODING_TEAM_ID from environment variable")
            except ValueError:
                raise ValueError("Invalid CODING_TEAM_ID in environment variable")

        if os.getenv('NEXUS_URL'):
            config.nexus_url = os.getenv('NEXUS_URL')
            logger.info("Using NEXUS_URL from environment variable")

        if os.getenv('NEXUS_USERNAME'):
            config.nexus_username = os.getenv('NEXUS_USERNAME')
            logger.info("Using NEXUS_USERNAME from environment variable")

        if os.getenv('NEXUS_PASSWORD'):
            config.nexus_password = os.getenv('NEXUS_PASSWORD')
            logger.info("Using NEXUS_PASSWORD from environment variable")

        if os.getenv('NEXUS_REPOSITORY'):
            config.nexus_repository = os.getenv('NEXUS_REPOSITORY')
            logger.info("Using NEXUS_REPOSITORY from environment variable")

        if os.getenv('NEXUS_SNAPSHOT_REPOSITORY'):
            config.nexus_snapshot_repository = os.getenv('NEXUS_SNAPSHOT_REPOSITORY')
            logger.info("Using NEXUS_SNAPSHOT_REPOSITORY from environment variable")

        return config

    def _validate_config(self, config_data: Dict[str, Any]) -> None:
        """
        验证配置数据

        Args:
            config_data: 配置数据

        Raises:
            ValueError: 配置验证失败
        """
        required_sections = ['coding', 'nexus', 'migration']

        for section in required_sections:
            if section not in config_data:
                raise ValueError(f"Missing required configuration section: {section}")

        # 验证 CODING 配置
        coding_config = config_data['coding']
        required_coding_fields = ['token', 'team_id']

        for field in required_coding_fields:
            if field not in coding_config:
                raise ValueError(f"Missing required CODING configuration: {field}")

        # 验证 Nexus 配置
        nexus_config = config_data['nexus']
        required_nexus_fields = ['url', 'username', 'password']

        for field in required_nexus_fields:
            if field not in nexus_config:
                raise ValueError(f"Missing required Nexus configuration: {field}")

        # 验证仓库配置（支持 repository 或 release_repo）
        if 'repository' not in nexus_config and 'release_repo' not in nexus_config:
            raise ValueError("Missing required Nexus configuration: repository or release_repo")

        # 验证迁移配置
        migration_config = config_data['migration']
        if 'project_names' not in migration_config:
            raise ValueError("Missing required migration configuration: project_names")

        logger.info("Configuration validation passed")

    def create_sample_config(self, output_file: Optional[str] = None) -> None:
        """
        创建示例配置文件

        Args:
            output_file: 输出文件路径
        """
        sample_config = {
            'coding': {
                'token': 'your_coding_token_here',
                'team_id': 123456
            },
            'nexus': {
                'url': 'http://localhost:8081',
                'username': 'admin',
                'password': 'admin123',
                'repository': 'maven-releases'
            },
            'migration': {
                'project_names': [
                    'project1',
                    'project2'
                ],
                'download_path': './downloads',
                'batch_size': 50,
                'parallel_downloads': 3
            },
            'logging': {
                'level': 'INFO',
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                'file': 'target/migration.log',
                'max_size_mb': 10,
                'backup_count': 5
            }
        }

        output_path = Path(output_file) if output_file else Path("config.sample.yaml")

        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                yaml.dump(sample_config, f, default_flow_style=False, allow_unicode=True, indent=2)

            logger.info(f"Sample configuration created: {output_path}")

        except Exception as e:
            logger.error(f"Failed to create sample configuration: {e}")
            raise

    def setup_logging(self, config_data: Optional[Dict[str, Any]] = None) -> None:
        """
        设置日志配置

        Args:
            config_data: 配置数据，如果为 None 则从配置文件加载
        """
        if config_data is None:
            config_data = self.load_config_dict()

        logging_config = config_data.get('logging', {})

        # 设置日志级别
        level = logging_config.get('level', 'INFO').upper()
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

        # 配置根日志记录器
        logging.basicConfig(
            level=getattr(logging, level),
            format=log_format,
            handlers=[
                logging.StreamHandler(),  # 控制台输出
            ]
        )

        # 添加文件处理器（如果配置了日志文件）
        log_file = logging_config.get('file')
        if log_file:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(logging.Formatter(log_format))
            logging.getLogger().addHandler(file_handler)

        logger.info(f"Logging configured with level: {level}")

    def load_config_dict(self) -> Dict[str, Any]:
        """
        加载配置为字典

        Returns:
            配置字典
        """
        if not self.config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_file}")

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)

        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            raise

    @staticmethod
    def load_from_env() -> MigrationConfig:
        """
        从环境变量加载配置

        Returns:
            迁移配置对象
        """
        return MigrationConfig(
            coding_token=os.getenv('CODING_TOKEN', ''),
            coding_team_id=int(os.getenv('CODING_TEAM_ID', '0')),
            nexus_url=os.getenv('NEXUS_URL', 'http://localhost:8081'),
            nexus_username=os.getenv('NEXUS_USERNAME', 'admin'),
            nexus_password=os.getenv('NEXUS_PASSWORD', 'admin123'),
            nexus_repository=os.getenv('NEXUS_REPOSITORY', 'maven-releases'),
            project_names=os.getenv('PROJECT_NAMES', '').split(',') if os.getenv('PROJECT_NAMES') else [],
            download_path=os.getenv('DOWNLOAD_PATH', './downloads'),
            batch_size=int(os.getenv('BATCH_SIZE', '100')),
            parallel_downloads=int(os.getenv('PARALLEL_DOWNLOADS', '5'))
        )