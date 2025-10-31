"""
内存流流水线迁移器 - 零磁盘占用的边下载边上传迁移
"""

import os
import json
import hashlib
import logging
import threading
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty
from dataclasses import dataclass
from tqdm import tqdm
import time
import io

from .models import MavenArtifact, MigrationConfig
from .coding_client import CodingClient
from .nexus_uploader import NexusUploader


logger = logging.getLogger(__name__)


@dataclass
class MemoryMigrationTask:
    """内存迁移任务"""
    artifact: MavenArtifact
    file_hash: Optional[str] = None
    download_success: bool = False
    upload_success: bool = False
    error_message: Optional[str] = None
    file_data: Optional[bytes] = None


class MemoryPipelineMigrator:
    """内存流流水线迁移器 - 零磁盘占用"""

    def __init__(self, config: MigrationConfig):
        """
        初始化内存流水线迁移器

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
        self.upload_workers = min(config.performance.max_workers // 2, 5)

        # 任务队列
        self.upload_queue = Queue(maxsize=50)  # 减小队列大小，减少内存占用
        self.completed_tasks = []
        self.failed_tasks = []

        # 统计信息
        self.stats = {
            'total_artifacts': 0,
            'downloaded': 0,
            'uploaded': 0,
            'download_failed': 0,
            'upload_failed': 0,
            'skipped_existing': 0
        }

        # 控制标志
        self.stop_event = threading.Event()

        # 迁移记录目录（固定目录，支持增量迁移）
        self.records_dir = Path("target")
        self.records_dir.mkdir(exist_ok=True)

        # 迁移记录文件和依赖列表（将在migrate_project中初始化）
        self.record_file = None
        self.uploaded_hashes: Set[str] = set()
        self.uploaded_dependencies = []

        # 内存限制（单位：字节）
        self.max_memory_usage = 100 * 1024 * 1024  # 100MB
        self.current_memory_usage = 0
        self.memory_lock = threading.Lock()

    def _load_migration_records(self) -> None:
        """加载已迁移记录"""
        try:
            if self.record_file.exists():
                with open(self.record_file, 'r', encoding='utf-8') as f:
                    records = json.load(f)
                    self.uploaded_hashes = set(records.get('uploaded_hashes', []))
                    self.uploaded_dependencies = records.get('uploaded_dependencies', [])
                logger.info(f"Loaded {len(self.uploaded_hashes)} migration records")
                if self.uploaded_dependencies:
                    logger.info(f"Previously uploaded {len(self.uploaded_dependencies)} dependencies")
        except Exception as e:
            logger.warning(f"Failed to load migration records: {e}")
            self.uploaded_hashes = set()
            self.uploaded_dependencies = []

    def _save_migration_records(self) -> None:
        """保存迁移记录"""
        try:
            records = {
                'uploaded_hashes': list(self.uploaded_hashes),
                'uploaded_dependencies': self.uploaded_dependencies,
                'last_updated': time.time()
            }
            with open(self.record_file, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(self.uploaded_hashes)} migration records")
        except Exception as e:
            logger.error(f"Failed to save migration records: {e}")

    def _calculate_file_hash(self, file_data: bytes) -> str:
        """计算文件哈希值"""
        return hashlib.sha256(file_data).hexdigest()

    def _check_if_already_uploaded(self, artifact: MavenArtifact) -> Optional[str]:
        """检查文件是否已经上传过"""
        # 生成唯一标识
        identifier = f"{artifact.group_id}:{artifact.artifact_id}:{artifact.version}:{artifact.packaging}"
        hash_identifier = hashlib.md5(identifier.encode()).hexdigest()

        if hash_identifier in self.uploaded_hashes:
            return hash_identifier
        return None

    def migrate_project(self, project_id: int, project_name: str) -> Dict[str, Any]:
        """
        迁移单个项目（内存流模式）

        Args:
            project_id: 项目 ID
            project_name: 项目名称

        Returns:
            迁移结果统计
        """
        logger.info(f"Starting memory pipeline migration for project: {project_name}")

        try:
            # 初始化迁移记录文件（按项目和项目ID区分）
            self.record_file = self.records_dir / f"migration_records_{project_name}_{project_id}.json"
            self._load_migration_records()

            # 获取所有制品
            all_artifacts = self._get_all_artifacts(project_id)
            self.stats['total_artifacts'] = len(all_artifacts)

            if not all_artifacts:
                logger.warning(f"No artifacts found for project: {project_name}")
                return self.stats

            # 过滤已上传的制品
            filtered_artifacts = []
            for artifact in all_artifacts:
                existing_hash = self._check_if_already_uploaded(artifact)
                if existing_hash:
                    self.stats['skipped_existing'] += 1
                    logger.debug(f"Skipping already uploaded: {artifact.file_path}")
                else:
                    filtered_artifacts.append(artifact)

            logger.info(f"Found {len(all_artifacts)} total artifacts, {len(filtered_artifacts)} to migrate "
                       f"({self.stats['skipped_existing']} already uploaded)")

            if not filtered_artifacts:
                logger.info("All artifacts have already been migrated")
                return self.stats

            # 启动下载和上传线程池
            with ThreadPoolExecutor(max_workers=self.download_workers + self.upload_workers) as executor:
                # 启动上传工作线程
                upload_futures = []
                for i in range(self.upload_workers):
                    future = executor.submit(self._upload_worker)
                    upload_futures.append(future)

                # 启动下载任务
                download_futures = []
                progress_bar = tqdm(total=len(filtered_artifacts), desc="Memory Pipeline",
                                  unit="files", postfix={"down": 0, "up": 0, "skip": self.stats['skipped_existing']})

                for artifact in filtered_artifacts:
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
                queue_wait_count = 0
                max_queue_wait = 600  # 最大等待60秒
                while not self.upload_queue.empty() and queue_wait_count < max_queue_wait:
                    queue_wait_count += 1
                    if queue_wait_count % 50 == 0:  # 每5秒打印一次
                        logger.info(f"Upload queue size: {self.upload_queue.qsize()}, waiting... ({queue_wait_count * 0.1:.1f}s)")
                    time.sleep(0.1)

                if not self.upload_queue.empty():
                    logger.warning(f"Upload queue not empty after timeout, {self.upload_queue.qsize()} items remaining")

                # 停止上传工作线程
                self.stop_event.set()

                # 等待上传线程完成
                for future in upload_futures:
                    future.result()

                progress_bar.close()

        except Exception as e:
            logger.error(f"Memory pipeline migration failed: {e}")
        finally:
            # 保存迁移记录
            self._save_migration_records()

        # 生成最终统计
        self._generate_final_stats()

        # 显示已上传的依赖汇总
        self._display_uploaded_dependencies_summary()

        return self.stats

    def _generate_final_stats(self) -> None:
        """生成最终统计信息"""
        logger.info("=" * 60)
        logger.info("📊 MEMORY PIPELINE MIGRATION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"[OK] Total artifacts processed: {self.stats['total_artifacts']}")
        logger.info(f"⬇️  Downloaded: {self.stats['downloaded']}")
        logger.info(f"⬆️  Uploaded: {self.stats['uploaded']}")
        logger.info(f"⏭️  Skipped (already uploaded): {self.stats['skipped_existing']}")
        logger.info(f"[ERROR] Download failed: {self.stats['download_failed']}")
        logger.info(f"[ERROR] Upload failed: {self.stats['upload_failed']}")
        logger.info("=" * 60)

    def _display_uploaded_dependencies_summary(self) -> None:
        """显示已上传依赖的汇总信息"""
        if not self.uploaded_dependencies:
            logger.info("[INFO] No new dependencies uploaded in this session")
            return

        logger.info("")
        logger.info("[INFO] UPLOADED DEPENDENCIES SUMMARY")
        logger.info("=" * 60)

        # 按group_id和artifact_id分组显示
        grouped_deps = {}
        for dep in self.uploaded_dependencies:
            key = f"{dep['group_id']}:{dep['artifact_id']}"
            if key not in grouped_deps:
                grouped_deps[key] = []
            grouped_deps[key].append(dep)

        for group_key, deps in sorted(grouped_deps.items()):
            logger.info(f"📋 {group_key}")
            for dep in sorted(deps, key=lambda x: x['version']):
                logger.info(f"   🏷️  {dep['version']} ({dep['packaging']}) - {dep['repository']}")

        logger.info("=" * 60)
        logger.info(f"📈 Total dependencies uploaded: {len(self.uploaded_dependencies)}")
        logger.info("")

    def _get_all_artifacts(self, project_id: int) -> List[MavenArtifact]:
        """获取所有制品"""
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
        下载制品到内存并加入上传队列

        Args:
            artifact: 制品信息
            progress_bar: 进度条

        Returns:
            下载是否成功
        """
        if self.stop_event.is_set():
            return False

        # 检查是否已经上传过
        existing_hash = self._check_if_already_uploaded(artifact)
        if existing_hash:
            logger.info(f"⏭️  SKIP: {artifact.group_id}:{artifact.artifact_id}:{artifact.version} already uploaded")
            self.stats['skipped_existing'] += 1
            progress_bar.set_postfix({"down": self.stats['downloaded'],
                                       "up": self.stats['uploaded'],
                                       "skip": self.stats['skipped_existing']})
            return True

        task = MemoryMigrationTask(artifact=artifact)

        try:
            # 检查内存使用限制
            with self.memory_lock:
                if self.current_memory_usage > self.max_memory_usage:
                    logger.warning(f"Memory usage limit reached: {self.current_memory_usage}/{self.max_memory_usage} bytes, waiting...")
                    wait_count = 0
                    max_wait_time = 300  # 最大等待30秒
                    while self.current_memory_usage > self.max_memory_usage * 0.5:
                        wait_count += 1
                        if wait_count % 50 == 0:  # 每5秒打印一次
                            logger.info(f"Waiting for memory release: {self.current_memory_usage} bytes (waited {wait_count * 0.1:.1f}s)")
                        if wait_count >= max_wait_time:  # 超时保护
                            logger.error(f"Memory wait timeout after {max_wait_time * 0.1:.1f}s, forcing continue")
                            break
                        time.sleep(0.1)

            # 下载文件到内存
            file_data = self._download_to_memory(artifact)

            if file_data:
                task.file_data = file_data
                task.file_hash = self._calculate_file_hash(file_data)
                task.download_success = True
                self.stats['downloaded'] += 1

                # 更新内存使用量
                with self.memory_lock:
                    self.current_memory_usage += len(file_data)

                # 加入上传队列
                try:
                    self.upload_queue.put(task, timeout=30)
                except Exception as queue_error:
                    logger.error(f"Failed to add task to upload queue: {queue_error}")
                    task.error_message = f"Queue error: {queue_error}"
                    self.stats['upload_failed'] += 1
                    self.failed_tasks.append(task)
                    return False

                logger.debug(f"Downloaded and queued: {artifact.file_path} ({len(file_data)} bytes)")

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
        progress_bar.set_postfix({"down": self.stats['downloaded'],
                                   "up": self.stats['uploaded'],
                                   "skip": self.stats['skipped_existing']})
        progress_bar.update(1)

        return task.download_success

    def _download_to_memory(self, artifact: MavenArtifact) -> Optional[bytes]:
        """下载文件到内存"""
        try:
            # 创建临时目录避免权限问题
            temp_dir = tempfile.mkdtemp()
            temp_file_path = os.path.join(temp_dir, f"temp_{hash(artifact.file_path)}.tmp")

            try:
                success = self.coding_client.download_artifact(
                    artifact.file_path.split('/')[0],  # project_name from file_path
                    "releases" if "releases" in artifact.file_path else "snapshots",
                    artifact.file_path,
                    temp_file_path,
                    getattr(artifact, 'download_url', None)
                )

                if success and os.path.exists(temp_file_path):
                    # 读取文件到内存
                    with open(temp_file_path, 'rb') as f:
                        file_data = f.read()
                    return file_data
                else:
                    return None

            finally:
                # 清理临时文件和目录
                try:
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)
                    os.rmdir(temp_dir)
                except Exception:
                    pass  # 忽略清理错误

        except Exception as e:
            logger.error(f"Failed to download {artifact.file_path} to memory: {e}")
            return None

    def _upload_worker(self) -> None:
        """上传工作线程"""
        logger.info("Memory upload worker started")

        # 记录保存计数器和状态报告
        save_counter = 0
        status_counter = 0

        while not self.stop_event.is_set():
            try:
                # 定期报告状态（每30秒）
                status_counter += 1
                if status_counter % 300 == 0:  # 300 * 0.1s = 30s
                    logger.info(f"Upload worker status - Memory usage: {self.current_memory_usage}/{self.max_memory_usage} bytes, "
                               f"Queue size: {self.upload_queue.qsize()}, Uploaded: {self.stats['uploaded']}, "
                               f"Failed: {self.stats['upload_failed']}")

                # 从队列获取任务
                task = self.upload_queue.get(timeout=1.0)

                try:
                    if task.download_success and task.file_data:
                        # 创建临时目录和文件用于上传
                        temp_dir = tempfile.mkdtemp()
                        temp_file_path = os.path.join(temp_dir, f"upload_{hash(task.artifact.file_path)}.tmp")

                        try:
                            # 写入临时文件
                            with open(temp_file_path, 'wb') as temp_file:
                                temp_file.write(task.file_data)
                                temp_file.flush()

                            # 上传文件
                            maven_path = self._convert_to_maven_path(task.artifact)
                            result = self.nexus_uploader.upload_file(
                                Path(temp_file_path), maven_path
                            )

                            if result.get('success'):
                                task.upload_success = True
                                self.stats['uploaded'] += 1

                                # 记录已上传的依赖信息
                                repository_name = task.artifact.repository or "Unknown"
                                file_name = task.artifact.file_path.split('/')[-1] if task.artifact.file_path else "Unknown"
                                dependency_info = {
                                    'group_id': task.artifact.group_id,
                                    'artifact_id': task.artifact.artifact_id,
                                    'version': task.artifact.version,
                                    'packaging': task.artifact.packaging,
                                    'repository': repository_name,
                                    'filename': file_name,
                                    'upload_time': time.time()
                                }
                                self.uploaded_dependencies.append(dependency_info)

                                # 记录已上传的文件 - 使用Maven坐标哈希而不是文件内容哈希
                                identifier = f"{task.artifact.group_id}:{task.artifact.artifact_id}:{task.artifact.version}:{task.artifact.packaging}"
                                maven_hash = hashlib.md5(identifier.encode()).hexdigest()
                                self.uploaded_hashes.add(maven_hash)

                                # 清晰显示上传成功的依赖
                                logger.info(f"[OK] UPLOADED DEPENDENCY: {task.artifact.group_id}:{task.artifact.artifact_id}:{task.artifact.version} ({task.artifact.packaging})")
                                logger.info(f"   Repository: {repository_name}")
                                logger.info(f"   Filename: {file_name}")

                                # 定期保存记录（每10个上传保存一次）
                                save_counter += 1
                                if save_counter % 10 == 0:
                                    self._save_migration_records()
                            else:
                                task.error_message = result.get('error', 'Upload failed')
                                self.stats['upload_failed'] += 1
                                self.failed_tasks.append(task)

                        finally:
                            # 清理临时文件和目录
                            try:
                                if os.path.exists(temp_file_path):
                                    os.unlink(temp_file_path)
                                os.rmdir(temp_dir)
                            except Exception:
                                pass  # 忽略清理错误

                except Exception as e:
                    task.error_message = str(e)
                    self.stats['upload_failed'] += 1
                    self.failed_tasks.append(task)
                    logger.error(f"Failed to upload {task.artifact.file_path}: {e}")

                finally:
                    # 释放内存（重要：确保总是释放内存）
                    if task.file_data:
                        file_size = len(task.file_data)
                        with self.memory_lock:
                            self.current_memory_usage -= file_size
                        logger.debug(f"Released {file_size} bytes from memory, current usage: {self.current_memory_usage}")
                        task.file_data = None

                    # 标记任务完成
                    try:
                        self.upload_queue.task_done()
                    except Exception as task_done_error:
                        logger.error(f"Failed to mark task as done: {task_done_error}")

            except Empty:
                # 队列为空，继续等待
                continue
            except Exception as e:
                logger.error(f"Upload worker error: {e}")
                # 确保在异常情况下也等待一小段时间，避免CPU占用过高
                time.sleep(0.1)

        logger.info("Memory upload worker stopped - Final memory usage: {self.current_memory_usage} bytes")

    def _convert_to_maven_path(self, artifact: MavenArtifact) -> str:
        """转换为 Maven 路径格式"""
        parts = artifact.file_path.split('/')
        if len(parts) >= 4:
            group_id = '.'.join(parts[:-3])
            artifact_id = parts[-3]
            version = parts[-2]
            filename = parts[-1]

            return f"{group_id.replace('.', '/')}/{artifact_id}/{version}/{filename}"

        return artifact.file_path

    def _generate_final_stats(self) -> None:
        """生成最终统计信息"""
        logger.info("=== Memory Pipeline Migration Statistics ===")
        logger.info(f"Total artifacts: {self.stats['total_artifacts']}")
        logger.info(f"Skipped (already uploaded): {self.stats['skipped_existing']}")
        logger.info(f"Downloaded: {self.stats['downloaded']}")
        logger.info(f"Download failed: {self.stats['download_failed']}")
        logger.info(f"Uploaded: {self.stats['uploaded']}")
        logger.info(f"Upload failed: {self.stats['upload_failed']}")

        if self.failed_tasks:
            logger.warning(f"Failed tasks: {len(self.failed_tasks)}")
            for task in self.failed_tasks[:5]:  # 只显示前5个错误
                logger.warning(f"  - {task.artifact.file_path}: {task.error_message}")

        processed = self.stats['uploaded'] + self.stats['upload_failed']
        success_rate = (self.stats['uploaded'] / processed * 100) if processed > 0 else 0
        logger.info(f"Upload success rate: {success_rate:.1f}%")