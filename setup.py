from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="print-test-stand",
    version="0.1.0",
    author="Test Stand Developer",
    description="Тестовый стенд для валидации сценариев печати Pantum BM5100ADN",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.10",
    install_requires=[
        "fastapi>=0.104.0",
        "uvicorn[standard]>=0.24.0",
        "pydantic>=2.5.0",
        "pydantic-settings>=2.1.0",
        "pyyaml>=6.0.1",
        "pypdf>=3.17.0",
        "python-docx>=1.1.0",
        "pillow>=10.1.0",
        "aiofiles>=23.2.0",
        "aiohttp>=3.9.0",
        "pytest>=7.4.0",
        "pytest-asyncio>=0.21.0",
        "pytest-benchmark>=4.0.0",
        "httpx>=0.25.0",
        "structlog>=23.2.0",
        "click>=8.1.0",
        "rich>=13.7.0",
    ],
    extras_require={
        "windows": ["pywin32>=306"],
        "snmp": ["pysnmp>=4.4.12"],
        "metrics": ["prometheus-client>=0.19.0"],
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.1.0",
            "mypy>=1.7.0",
            "ruff>=0.1.6",
        ],
    },
    entry_points={
        "console_scripts": [
            "print-test=run_tests:cli",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["*.yaml", "*.yml"],
    },
)
