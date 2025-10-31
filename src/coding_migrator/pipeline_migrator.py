"""
流水线迁移器 - 实现边下载边上传的高效迁移
"""

import os
import logging
import tempfile
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty
from dataclasses import dataclass
from tqdm import tqdm
import time

from .models import MavenArtifact, MigrationConfig
from .coding_client import CodingClient
from .nexus_uploader import NexusUploader


logger = logging.getLogger(__name__)


@dataclass
class MigrationTask:
    """迁移任务"""
    artifact: MavenArtifact
    temp_file_path: Optional[Path] = None
    download_success: bool = False
    upload_success: bool = False
    error_message: Optional[str] = None


class PipelineMigrator:
    """流水线迁移器 - 边下载边上传"""

    def __init__(self, config: MigrationConfig):
        """
        初始化流水线迁移器

        Args:
            config: 迁移配置
        """
        self.config = config
        self.coding_client = CodingClient(
            config.coding_token,
            config.coding_team_id,
            config.maven_repositories,
            config.pagination,
            config.performance.max_workers,
            requests_per_second=config.rate_limit.requests_per_second
        )
        self.nexus_uploader = NexusUploader(config)

        # 性能配置
        self.download_workers = config.performance.max_workers
        self.upload_workers = min(config.performance.max_workers // 2, 5)  # 上传线程数稍少

        # 任务队列
        self.upload_queue = Queue(maxsize=100)  # 限制队列大小避免内存溢出
        self.completed_tasks = []
        self.failed_tasks = []

        # 统计信息
        self.stats = {
            'total_artifacts': 0,
            'downloaded': 0,
            'uploaded': 0,
            'download_failed': 0,
            'upload_failed': 0
        }

        # 控制标志
        self.stop_event = threading.Event()
        self.temp_dir = None

    def migrate_project(self, project_id: int, project_name: str) -> Dict[str, Any]:
        """
        迁移单个项目（流水线模式）

        Args:
            project_id: 项目 ID
            project_name: 项目名称

        Returns:
            迁移结果统计
        """
        logger.info(f"Starting pipeline migration for project: {project_name}")

        try:
            # 创建临时目录
            self.temp_dir = Path(tempfile.mkdtemp(prefix=f"migration_{project_name}_"))
            logger.info(f"Created temporary directory: {self.temp_dir}")

            # 获取所有制品
            all_artifacts = self._get_all_artifacts(project_id)
            self.stats['total_artifacts'] = len(all_artifacts)

            if not all_artifacts:
                logger.warning(f"No artifacts found for project: {project_name}")
                return self.stats

            logger.info(f"Found {len(all_artifacts)} artifacts to migrate")

            # 启动下载和上传线程池
            with ThreadPoolExecutor(max_workers=self.download_workers + self.upload_workers) as executor:
                # 启动上传工作线程
                upload_futures = []
                for i in range(self.upload_workers):
                    future = executor.submit(self._upload_worker)
                    upload_futures.append(future)

                # 启动下载任务
                download_futures = []
                progress_bar = tqdm(total=len(all_artifacts), desc="Pipeline Migration",
                                  unit="files", postfix={"down": 0, "up": 0})

                for artifact in all_artifacts:
                    future = executor.submit(self._download_and_queue, artifact, progress_bar)
                    download_futures.append(future)

                # 等待所有下载任务完成
                for future in as_completed(download_futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Download task failed: {e}")

                # 等待上传队列清空
                logger.info("Waiting for upload queue to empty...")
                while not self.upload_queue.empty():
                    time.sleep(0.1)

                # 停止上传工作线程
                self.stop_event.set()

                # 等待上传线程完成
                for future in upload_futures:
                    future.result()

                progress_bar.close()

        except Exception as e:
            logger.error(f"Pipeline migration failed: {e}")
        finally:
            # 清理临时目录
            if self.temp_dir and self.temp_dir.exists():
                self._cleanup_temp_dir()

        # 生成最终统计
        self._generate_final_stats()

        return self.stats

    def _get_all_artifacts(self, project_id: int) -> List[MavenArtifact]:
        """
        获取所有制品

        Args:
            project_id: 项目 ID

        Returns:
            制品列表
        """
        all_artifacts = []

        # 获取项目名称
        project_name = self.coding_client.get_project_name_by_id(project_id)

        # 获取制品仓库
        repositories = self.coding_client.get_artifact_repositories(project_id)
        maven_repos = [repo for repo in repositories if repo.get('Type') == 3]

        for repo in maven_repos:
            repo_name = repo.get('Name', '')
            logger.info(f"Processing repository: {repo_name}")

            try:
                artifacts = self.coding_client.get_maven_artifacts(
                    project_id, repo_name, self.config.maven_filter
                )
                all_artifacts.extend(artifacts)
                logger.info(f"Found {len(artifacts)} artifacts in repository: {repo_name}")

            except Exception as e:
                logger.error(f"Failed to get artifacts from repository {repo_name}: {e}")

        return all_artifacts

    def _download_and_queue(self, artifact: MavenArtifact, progress_bar: tqdm) -> bool:
        """
        下载制品并加入上传队列

        Args:
            artifact: 制品信息
            progress_bar: 进度条

        Returns:
            下载是否成功
        """
        if self.stop_event.is_set():
            return False

        task = MigrationTask(artifact=artifact)

        try:
            # 创建临时文件路径
            temp_file_path = self.temp_dir / artifact.file_path.split('/')[-1]
            temp_file_path.parent.mkdir(parents=True, exist_ok=True)
            task.temp_file_path = temp_file_path

            # 下载文件
            success = self.coding_client.download_artifact(
                artifact.file_path.split('/')[0],  # project_name from file_path
                "releases" if "releases" in artifact.file_path else "snapshots",
                artifact.file_path,
                str(temp_file_path),
                getattr(artifact, 'download_url', None)
            )

            if success and temp_file_path.exists():
                task.download_success = True
                self.stats['downloaded'] += 1

                # 加入上传队列（阻塞等待队列有空间）
                self.upload_queue.put(task, timeout=30)

                logger.debug(f"Downloaded and queued: {artifact.file_path}")

            else:
                task.error_message = "Download failed"
                self.stats['download_failed'] += 1
                self.failed_tasks.append(task)

        except Exception as e:
            task.error_message = str(e)
            self.stats['download_failed'] += 1
            self.failed_tasks.append(task)
            logger.error(f"Failed to download {artifact.file_path}: {e}")

        # 更新进度条
        progress_bar.set_postfix({"down": self.stats['downloaded'], "up": self.stats['uploaded']})
        progress_bar.update(1)

        return task.download_success

    def _upload_worker(self) -> None:
        """
        上传工作线程
        """
        logger.info("Upload worker started")

        while not self.stop_event.is_set():
            try:
                # 从队列获取任务（超时1秒）
                task = self.upload_queue.get(timeout=1.0)

                try:
                    if task.download_success and task.temp_file_path:
                        # 上传文件
                        maven_path = self._convert_to_maven_path(task.artifact)
                        result = self.nexus_uploader.upload_file(
                            task.temp_file_path, maven_path
                        )

                        if result.get('success'):
                            task.upload_success = True
                            self.stats['uploaded'] += 1
                            logger.debug(f"Uploaded: {task.artifact.file_path}")
                        else:
                            task.error_message = result.get('error', 'Upload failed')
                            self.stats['upload_failed'] += 1
                            self.failed_tasks.append(task)

                except Exception as e:
                    task.error_message = str(e)
                    self.stats['upload_failed'] += 1
                    self.failed_tasks.append(task)
                    logger.error(f"Failed to upload {task.artifact.file_path}: {e}")

                finally:
                    # 清理临时文件
                    if task.temp_file_path and task.temp_file_path.exists():
                        try:
                            task.temp_file_path.unlink()
                        except Exception as e:
                            logger.warning(f"Failed to delete temp file {task.temp_file_path}: {e}")

                    # 标记任务完成
                    self.upload_queue.task_done()

            except Empty:
                # 队列为空，继续等待
                continue
            except Exception as e:
                logger.error(f"Upload worker error: {e}")

        logger.info("Upload worker stopped")

    def _convert_to_maven_path(self, artifact: MavenArtifact) -> str:
        """
        转换为 Maven 路径格式

        Args:
            artifact: 制品信息

        Returns:
            Maven 路径
        """
        # 从 file_path 解析 Maven 坐标
        parts = artifact.file_path.split('/')
        if len(parts) >= 4:
            group_id = '.'.join(parts[:-3])
            artifact_id = parts[-3]
            version = parts[-2]
            filename = parts[-1]

            return f"{group_id.replace('.', '/')}/{artifact_id}/{version}/{filename}"

        return artifact.file_path

    def _cleanup_temp_dir(self) -> None:
        """
        清理临时目录
        """
        try:
            if self.temp_dir and self.temp_dir.exists():
                import shutil
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temporary directory: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temporary directory: {e}")

    def _generate_final_stats(self) -> None:
        """
        生成最终统计信息
        """
        logger.info("=== Pipeline Migration Statistics ===")
        logger.info(f"Total artifacts: {self.stats['total_artifacts']}")
        logger.info(f"Downloaded: {self.stats['downloaded']}")
        logger.info(f"Download failed: {self.stats['download_failed']}")
        logger.info(f"Uploaded: {self.stats['uploaded']}")
        logger.info(f"Upload failed: {self.stats['upload_failed']}")

        if self.failed_tasks:
            logger.warning(f"Failed tasks: {len(self.failed_tasks)}")
            for task in self.failed_tasks[:10]:  # 只显示前10个错误
                logger.warning(f"  - {task.artifact.file_path}: {task.error_message}")

        success_rate = (self.stats['uploaded'] / self.stats['total_artifacts'] * 100) if self.stats['total_artifacts'] > 0 else 0
        logger.info(f"Overall success rate: {success_rate:.1f}%")