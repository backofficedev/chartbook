#!/usr/bin/env python
"""Pre-generation hook for validating cookiecutter inputs."""

import re
import sys

# Validate project_slug is a valid Python identifier
project_slug = {{ cookiecutter.project_slug | tojson }}

if not re.match(r"^[a-z][a-z0-9_]*$", project_slug):
    print(f"ERROR: '{project_slug}' cannot be the project's folder name.")
    print("The folder name (the second question) must:")
    print("  - Start with a lowercase letter")
    print("  - Contain only lowercase letters, numbers, and underscores")
    # What the second question offered, made from the first answer
    suggested = {{ cookiecutter.project_name.lower().replace(' ', '_').replace('-', '_') | tojson }}
    if suggested != project_slug and re.match(r"^[a-z][a-z0-9_]*$", suggested):
        print(f"Nothing was created. Run it again and press Enter at the second question to take '{suggested}'.")
    else:
        print("Nothing was created. Run it again and type a folder name like 'my_project' at the second question.")
    sys.exit(1)

# Validate email format (basic check)
author_email = "{{ cookiecutter.author_email }}"
if author_email and "@" not in author_email:
    print(f"WARNING: '{author_email}' doesn't look like a valid email address.")

# Validate environment manager compatibility with R scripts
include_r_scripts = "{{ cookiecutter.include_r_scripts }}"
environment_manager = "{{ cookiecutter.environment_manager }}"

if include_r_scripts.lower() in ("y", "yes", "true", "1") and environment_manager in ["pip", "uv"]:
    print("ERROR: R scripts require conda or pixi for R package management.")
    print("Please choose 'conda' or 'pixi' as your environment manager.")
    sys.exit(1)

print(f"Creating project: {project_slug}")
