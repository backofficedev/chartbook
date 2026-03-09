# Getting Started

How to set up and run the yield curve analysis pipeline.

## Prerequisites

- Python 3.10+
- Required packages: `pip install -r requirements.txt`

## Running the Pipeline

1. Pull the data: `doit pull_data`
2. Run analysis: `doit run_notebooks`
3. Build the site: `chartbook build`

## Viewing the Output

After building, open `docs/index.html` in your browser or serve locally:

```console
python -m http.server -d ./docs
```
