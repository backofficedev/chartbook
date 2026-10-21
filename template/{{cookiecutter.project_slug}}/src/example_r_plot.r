library(arrow)
library(fs)
library(ggplot2)
library(tidyverse)

## Prevent the creation of Rplots.pdf
pdf(NULL)
## Another solution is this:
# library(Cairo)
# CairoPNG(file = path(OUTPUT_DIR, "example_r_plot.png"))

#### <<< Load .env
library(fs)
library(dotenv)

if (file.exists(".env")) {
  dotenvpath <- path(".env")
} else {
  dotenvpath <- path("../.env")
}
load_dot_env(dotenvpath)
DATA_DIR <- Sys.getenv("DATA_DIR")
OUTPUT_DIR <- Sys.getenv("OUTPUT_DIR")
#### >>>


# Print the value to stdout
# cat("DATA_DIR:", DATA_DIR, "\n")

{% if cookiecutter.include_fred -%}
# Use base R
# filepath <- file.path(DATA_DIR, "fred.parquet")
# Use fs
filepath <- path(DATA_DIR, "fred.parquet")

# Read the Parquet file into a tibble
fred_tibble <- read_parquet(filepath)
{% else -%}
# FRED was not selected for this project, so simulate a quarterly GDP series to
# stand in for the one that pull_fred.py would otherwise provide.
set.seed(100)
dates <- seq(as.Date("1947-01-01"), as.Date("2023-10-01"), by = "quarter")
growth <- rnorm(length(dates), mean = 0.008, sd = 0.01)
fred_tibble <- tibble(DATE = dates, GDP = 100 * exp(cumsum(growth)))
{% endif %}
# Create plot of GDP
ggplot(fred_tibble %>% drop_na(GDP), 
    aes(x = DATE, y = GDP)) +
    geom_line() +
{%- if cookiecutter.include_fred %}
    labs(x = "DATE", y = "GDP") +
{%- else %}
    labs(x = "DATE", y = "Simulated GDP") +
{%- endif %}
    theme_minimal()


filepath <- path(OUTPUT_DIR, "example_r_plot.png")
ggsave(filepath)
