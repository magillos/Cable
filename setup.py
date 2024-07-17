from setuptools import setup, find_packages

setup(
    name="cable",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "PyQt5",
    ],
    entry_points={
        "console_scripts": [
            "cable=cable.Cable:main",
        ],
    },
    # Include additional files
    package_data={
        "cable": ["*.ui", "*.png", "*.ico"],
    },
)
