from setuptools import setup, find_packages

setup(
    name="sus-scanner",
    version="0.1.0",
    description="Chess.com Daily Suspicion Scanner – Tournament vs Non-Tournament play analysis",
    author="Your Name",
    author_email="your@email.com",
    url="https://github.com/your-org/sus-scanner",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=["requests>=2.25.0"],
    extras_require={"dev": ["pytest>=7.0", "black", "flake8"]},
    entry_points={"console_scripts": ["sus-scanner = sus_scanner.cli:main"]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
)
