from typing import List

from setuptools import find_packages, setup

HYPHEN_E_DOT = "-e ."


def get_requirements(file_path: str) -> List[str]:
    """Reads requirements.txt, skipping blank lines, comments and the '-e .' line."""
    with open(file_path, encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines()]
    return [line for line in lines if line and not line.startswith("#") and line != HYPHEN_E_DOT]


setup(
    name="voice-agent-cafe",
    version="0.1.0",
    description="Restaurant voice agent: table booking and delivery orders",
    packages=find_packages(),
    install_requires=get_requirements("requirements.txt"),
    python_requires=">=3.11",
)
