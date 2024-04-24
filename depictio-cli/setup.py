from setuptools import setup, find_packages

setup(
    name="depictio-cli",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "bleach",
        "bson",
        "httpx",
        "pydantic==1.10.10",
        "devtools",
        "python-jose",
        "pyyaml",
        "typer",
        "email-validator==1.1.3"
    ],
    entry_points={
        "console_scripts": [
            "depictio-cli=depictio_cli.depictio_cli:main"
        ]
    },
    author="Your Name",
    author_email="your.email@example.com",
    description="A brief description of what your project does",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url="http://github.com/depictio/depictio",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
)
