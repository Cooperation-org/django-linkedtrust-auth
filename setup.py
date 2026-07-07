from setuptools import setup, find_packages

setup(
    name="django-linkedtrust-auth",
    version="1.1.0",
    description="LinkedTrust OIDC authentication for Django (works with Taiga, Odoo, etc.)",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Cooperation.org",
    author_email="dev@cooperation.org",
    url="https://github.com/Cooperation-org/django-linkedtrust-auth",
    license="MPL-2.0",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "django>=3.2",
        "requests>=2.20",
    ],
    classifiers=[
        "Framework :: Django",
        "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
        "Programming Language :: Python :: 3",
    ],
)
