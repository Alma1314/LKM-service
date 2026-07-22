"""全局 pytest fixtures 和配置。"""
import os

# 确保测试始终以 test 标志运行，允许弱 JWT 密钥
os.environ["PYTEST_RUNNING"] = "1"
