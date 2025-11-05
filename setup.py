#encoding="utf-8"
import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="PyXcpcalibApi", # Replace with your own username
    version="0.0.2",
    author="Sgnes",
    author_email="sgnes0514@gmai.com",
    description="High lelve API to access calibration and measurement.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/sgnes/XCP-Calibration-Api",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
     "pya2lparser", "pyxcpcanmaster"
      ],
    packages=[
        'xcp_calib_api'
        ],

    python_requires='>=3.8',
)