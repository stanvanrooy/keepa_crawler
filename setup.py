from setuptools import setup

setup(
    name="keepa_crawler",
    version="1.0.0",
    package_dir={"keepa_crawler": "src"},
    packages=["keepa_crawler"],
    install_requires=[
        'curl-cffi>=0.5.8',
    ],
    description="A client to crawl Keepa's historical Amazon product data",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author="Stan van Rooy",
    author_email="stanvanrooy6@gmail.com",
    url="https://github.com/stanvanrooy/keepa_crawler",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
)
