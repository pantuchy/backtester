from setuptools import setup, find_packages

classifiers = [
	"Development Status :: 5 - Production/Stable",
	"Intended Audience :: Education",
	"Operating System :: Microsoft :: Windows :: Windows 10",
	"License :: OSI Approved :: MIT License",
	"Programming Language :: Python :: 3"
]

setup(
	name="pantuchy-backtester",
	version="1.0.0",
	description="Backtesting library.",
	long_description=open("README.txt").read() + "\n\n" + open("CHANGELOG.txt").read(),
	url="https://github.com/pantuchy/backtester",
	author="Maksim Pol",
	author_email="p.m.n@outlook.com",
	license="MIT",
	classifiers=classifiers,
	keywords="backtesting",
	packages=find_packages(),
	python_requires=">=3.8",
	install_requires=["numpy", "pandas", "bokeh"]
)
