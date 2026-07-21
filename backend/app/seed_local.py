"""Backward-compatible alias for the standard seed command."""
from .seed import seed


if __name__ == "__main__":
    result = seed("development")
    print(f"已同步 {result['users']} 个本地测试用户")
