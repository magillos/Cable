from setuptools import setup

setup(
    name='cable',
    version='0.4.1',
    py_modules=['Cable'],
    entry_points={
        'console_scripts': [
            'cable = Cable:main',
        ],
    },
)
