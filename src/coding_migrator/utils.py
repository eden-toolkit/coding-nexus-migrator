"""
工具函数
"""

import os
import sys
import time
import logging
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from functools import wraps


logger = logging.getLogger(__name__)


def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0, exceptions: tuple = (Exception,)):
    """
    重试装饰器

    Args:
        max_attempts: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff: 退避倍数
        exceptions: 需要重试的异常类型
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            current_delay = delay

            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    attempts += 1
                    if attempts >= max_attempts:
                        logger.error(f"Function {func.__name__} failed after {max_attempts} attempts: {e}")
                        raise

                    logger.warning(f"Function {func.__name__} failed (attempt {attempts}/{max_attempts}): {e}")
                    logger.info(f"Retrying in {current_delay} seconds...")
                    time.sleep(current_delay)
                    current_delay *= backoff

        return wrapper
    return decorator


def validate_file_path(file_path: Union[str, Path], must_exist: bool = True) -> Path:
    """
    验证文件路径

    Args:
        file_path: 文件路径
        must_exist: 文件是否必须存在

    Returns:
        验证后的 Path 对象

    Raises:
        ValueError: 路径无效
        FileNotFoundError: 文件不存在（当 must_exist=True 时）
    """
    path = Path(file_path)

    if must_exist and not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if not path.parent.exists():
        raise ValueError(f"Parent directory does not exist: {path.parent}")

    return path


def ensure_directory(directory: Union[str, Path]) -> Path:
    """
    确保目录存在，不存在则创建

    Args:
        directory: 目录路径

    Returns:
        Path 对象
    """
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    return path


def calculate_file_hash(file_path: Union[str, Path], algorithm: str = 'md5') -> str:
    """
    计算文件哈希值

    Args:
        file_path: 文件路径
        algorithm: 哈希算法 (md5, sha1, sha256)

    Returns:
        哈希值
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    hash_func = getattr(hashlib, algorithm.lower())()

    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_func.update(chunk)

    return hash_func.hexdigest()


def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小

    Args:
        size_bytes: 文件大小（字节）

    Returns:
        格式化的文件大小字符串
    """
    if size_bytes == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1

    return f"{size_bytes:.2f} {size_names[i]}"


def format_duration(seconds: float) -> str:
    """
    格式化时间长度

    Args:
        seconds: 秒数

    Returns:
        格式化的时间字符串
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def safe_filename(filename: str) -> str:
    """
    生成安全的文件名

    Args:
        filename: 原始文件名

    Returns:
        安全的文件名
    """
    # 移除或替换不安全的字符
    unsafe_chars = '<>:"/\\|?*'
    for char in unsafe_chars:
        filename = filename.replace(char, '_')

    # 限制长度
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255-len(ext)] + ext

    return filename


def parse_maven_coordinates(coordinates: str) -> Dict[str, str]:
    """
    解析 Maven 坐标

    Args:
        coordinates: Maven 坐标 (groupId:artifactId:version:packaging)

    Returns:
        解析后的坐标字典
    """
    parts = coordinates.split(':')

    if len(parts) < 3:
        raise ValueError(f"Invalid Maven coordinates: {coordinates}")

    result = {
        'groupId': parts[0],
        'artifactId': parts[1],
        'version': parts[2],
        'packaging': parts[3] if len(parts) > 3 else 'jar'
    }

    return result


def maven_coordinates_to_path(coordinates: Dict[str, str]) -> str:
    """
    将 Maven 坐标转换为路径

    Args:
        coordinates: Maven 坐标字典

    Returns:
        Maven 路径
    """
    group_path = coordinates['groupId'].replace('.', '/')
    artifact_id = coordinates['artifactId']
    version = coordinates['version']
    packaging = coordinates['packaging']

    filename = f"{artifact_id}-{version}.{packaging}"
    return f"{group_path}/{artifact_id}/{version}/{filename}"


def merge_dicts(*dicts: Dict[str, Any]) -> Dict[str, Any]:
    """
    合并字典

    Args:
        dicts: 要合并的字典

    Returns:
        合并后的字典
    """
    result = {}
    for d in dicts:
        result.update(d)
    return result


def filter_dict(d: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    """
    过滤字典，只保留指定的键

    Args:
        d: 原始字典
        keys: 要保留的键列表

    Returns:
        过滤后的字典
    """
    return {k: v for k, v in d.items() if k in keys}


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    将列表分块

    Args:
        lst: 原始列表
        chunk_size: 块大小

    Returns:
        分块后的列表
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def truncate_string(s: str, max_length: int, suffix: str = "...") -> str:
    """
    截断字符串

    Args:
        s: 原始字符串
        max_length: 最大长度
        suffix: 后缀

    Returns:
        截断后的字符串
    """
    if len(s) <= max_length:
        return s

    return s[:max_length - len(suffix)] + suffix


def is_valid_url(url: str) -> bool:
    """
    验证 URL 是否有效

    Args:
        url: URL 字符串

    Returns:
        URL 是否有效
    """
    import re

    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    return url_pattern.match(url) is not None


def get_system_info() -> Dict[str, str]:
    """
    获取系统信息

    Returns:
        系统信息字典
    """
    import platform

    return {
        'platform': platform.platform(),
        'python_version': platform.python_version(),
        'architecture': platform.architecture()[0],
        'processor': platform.processor(),
        'hostname': platform.node()
    }


def setup_signal_handlers():
    """设置信号处理器"""
    import signal

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, exiting...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


class ProgressTracker:
    """进度跟踪器"""

    def __init__(self, total: int, description: str = "Progress"):
        """
        初始化进度跟踪器

        Args:
            total: 总数
            description: 描述信息
        """
        self.total = total
        self.current = 0
        self.description = description
        self.start_time = time.time()

    def update(self, increment: int = 1):
        """更新进度"""
        self.current += increment
        self._log_progress()

    def _log_progress(self):
        """记录进度"""
        if self.total > 0:
            percentage = (self.current / self.total) * 100
            elapsed = time.time() - self.start_time

            if self.current > 0:
                eta = (elapsed / self.current) * (self.total - self.current)
                eta_str = format_duration(eta)
            else:
                eta_str = "N/A"

            logger.info(f"{self.description}: {self.current}/{self.total} ({percentage:.1f}%) - ETA: {eta_str}")

    def finish(self):
        """完成进度"""
        elapsed = time.time() - self.start_time
        logger.info(f"{self.description} completed in {format_duration(elapsed)}")