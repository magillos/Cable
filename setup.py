from setuptools import setup

setup(
    name='cable',
    version='0.1.4',
    py_modules=['Cable'],
    entry_points={
        'console_scripts': [
            'cable = Cable:main',
        ],
    },
)
