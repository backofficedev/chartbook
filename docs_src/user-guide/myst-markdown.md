# Writing with MyST Markdown

ChartBook documentation is written using [MyST Markdown](https://myst-parser.readthedocs.io/),
a rich extension of Markdown that supports many features useful for technical documentation.

This guide covers the most commonly used MyST features for writing chart and pipeline documentation.

## Basic Formatting

### Tables

```markdown
|    Training   |   Validation   |
| :------------ | -------------: |
|        0      |        5       |
|     13720     |      2744      |
```

Renders as:

|    Training   |   Validation   |
| :------------ | -------------: |
|        0      |        5       |
|     13720     |      2744      |

## Admonitions

Admonitions are callout boxes that highlight important information:

````markdown
```{note}
Notes require **no** arguments, so content can start here.
```
````

```{note}
Notes require **no** arguments, so content can start here.
```

Other available admonitions:

```{tip}
This is an example of a tip directive.
```

```{warning}
This is an example of a warning directive.
```

```{important}
This is an example of an important directive.
```

## Mathematics

### Inline Math

Wrap inline equations in single dollar signs: `$z=\sqrt{x^2+y^2}$`

This renders as: $z=\sqrt{x^2+y^2}$

### Block Math

Use double dollar signs for display equations:

```markdown
$$
z=\sqrt{x^2+y^2}
$$
```

$$
z=\sqrt{x^2+y^2}
$$

### Labeled Equations

You can add labels to reference equations later:

````markdown
```{math}
:label: eq-example

z=\sqrt{x^2+y^2}
```
````

Reference with `{eq}`eq-example``.

## Code Blocks

Wrap inline code in backticks: `boolean example = true;`

For code blocks, use triple backticks with a language identifier:

````markdown
```python
note = "Python syntax highlighting"
print(note)
```
````

```python
note = "Python syntax highlighting"
print(note)
```

## Cross-References

MyST supports various cross-referencing directives:

- `{doc}`path/to/doc`` - Link to another document
- `{ref}`label`` - Link to a labeled section
- `{eq}`equation-label`` - Link to a labeled equation

## Learn More

For complete MyST documentation, visit:
- [MyST Parser Documentation](https://myst-parser.readthedocs.io/)
- [Sphinx Design](https://sphinx-design.readthedocs.io/) for grid layouts and cards
