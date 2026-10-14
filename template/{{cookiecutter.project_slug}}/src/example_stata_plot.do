* Load environment variables
doenv using ".env"

* Define file paths
{% if cookiecutter.include_fred -%}
local data_dir = "`r(DATA_DIR)'"
local output_dir = "`r(OUTPUT_DIR)'"

local filepath = "`data_dir'/fred.csv"
local output_filepath = "`output_dir'/example_stata_plot.png"

* Display the paths to verify
display "`filepath'"
display "`output_filepath'"

* Read the CSV file into memory
import delimited `filepath', clear

* Drop rows where GDP is missing
drop if missing(gdp)

* Convert DATE column from string to Stata date format
gen date_numeric = date(date, "YMD")
format date_numeric %td
{% else -%}
local output_dir = "`r(OUTPUT_DIR)'"

local output_filepath = "`output_dir'/example_stata_plot.png"

* Display the path to verify
display "`output_filepath'"

* FRED was not selected for this project, so simulate a quarterly GDP series
* to stand in for the one that pull_fred.py would otherwise provide.
clear
set seed 100
set obs 308
gen date_numeric = dofq(tq(1947q1) + _n - 1)
format date_numeric %td
gen gdp = 100 * exp(sum(rnormal(0.008, 0.01)))
{% endif %}
* Set the time variable
tsset date_numeric

* Generate the plot
{% if cookiecutter.include_fred -%}
twoway (tsline gdp), title("GDP over Time") xtitle("Date") ytitle("GDP")
{% else -%}
twoway (tsline gdp), title("Simulated GDP over Time") xtitle("Date") ytitle("GDP")
{% endif -%}
graph export "`output_filepath'", replace

* * Save the plot
* graph export `output_filepath', replace