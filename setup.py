import fastentrypoints
import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="botwfstools",
    version="1.0.0",
    author="leoetlino",
    author_email="leo@leolam.fr",
    description="Tools for exploring and editing Breath of the Wild's ROM",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/leoetlino/botwfstools",
    packages=setuptools.find_packages(),
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3 :: Only",
    ],
    include_package_data=True,
    python_requires='>=3.6',
    install_requires=['rstb~=1.0.1', 'sarc~=1.0.5', 'colorama~=0.3.9'],
    entry_points = {
        'console_scripts': [
            'botw-contentfs = botwfstools.botw_contentfs:cli_main',
            'botw-overlayfs = botwfstools.botw_overlayfs:cli_main',
            'botw-edit = botwfstools.botw_edit:cli_main',
            'botw-patcher = botwfstools.botw_patcher:cli_main',
        ]
    },
)
