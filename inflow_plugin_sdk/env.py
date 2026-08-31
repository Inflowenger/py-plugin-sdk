# Dotenv loading. Mirrors sdkv1/dotenv.go.
import os

from dotenv import load_dotenv


def load_env(path: str = ".env") -> None:
    """Load an env file into os.environ (defaults to ".env"), like Go's NewEnv.
    Missing files are ignored, matching godotenv.Load's best-effort behavior."""
    if not path:
        path = ".env"
    load_dotenv(path)


def get_env_var(key: str) -> str:
    """Read an env var, warning (but not failing) when unset — like Go's getEnvVar."""
    v = os.environ.get(key)
    if v is None:
        print(f"Environment variable not set {key}")
        return ""
    return v
