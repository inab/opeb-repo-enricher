# Installation instructions for OpenEBench repoEnricher

The python version of OpenEBench repoEnricher is based on standard Python libraries.

If you are interested in the development, the recommended approach is creating a virtual environment,
where to install all the dependencies declared a [dev-requirements.txt](dev-requirements.txt):

```bash
python3 -mvenv .full13
source .full13/bin/activate
pip install --upgrade pip wheel
pip install -r dev-requirements.txt
pre-commit install
```

One of these dependencies is [pre-commit](https://pre-commit.com/), which performs several checks
([ruff](https://docs.astral.sh/ruff/), [mypy](https://mypy-lang.org/), ...) declared at
[.pre-commit-config.yaml](.pre-commit-config.yaml).

Due the way mypy is installed, if you name in a different way the virtual environment,
you have to fix the path around line 33. 

# Metrics uploading to OpenEBench

This task is done by the scripts you can find at [opeb-submitter](opeb-submitter). Please follow install and usage instructions there.
