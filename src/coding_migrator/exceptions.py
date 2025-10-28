"""
自定义异常类
"""


class CodingMigratorError(Exception):
    """基础异常类"""
    pass


class ConfigurationError(CodingMigratorError):
    """配置错误"""
    pass


class ConnectionError(CodingMigratorError):
    """连接错误"""
    pass


class AuthenticationError(CodingMigratorError):
    """认证错误"""
    pass


class DownloadError(CodingMigratorError):
    """下载错误"""
    pass


class UploadError(CodingMigratorError):
    """上传错误"""
    pass


class APIError(CodingMigratorError):
    """API 错误"""
    def __init__(self, message: str, code: str = None, details: str = None):
        super().__init__(message)
        self.code = code
        self.details = details


class ProjectNotFoundError(CodingMigratorError):
    """项目未找到错误"""
    pass


class RepositoryNotFoundError(CodingMigratorError):
    """仓库未找到错误"""
    pass