# services/risk_service_r/install_packages.R

# Set a reliable CRAN mirror
options(repos = c(CRAN = "https://cloud.r-project.org/"))

# Use a writable user library when the default system library is not writable.
default_lib <- .libPaths()[1]
if (file.access(default_lib, 2) != 0) {
  user_lib <- Sys.getenv("R_LIBS_USER")
  if (!nzchar(user_lib)) {
    user_lib <- path.expand("~/R/library")
  }
  dir.create(user_lib, recursive = TRUE, showWarnings = FALSE)
  .libPaths(c(user_lib, .libPaths()))
  message("Using user library: ", user_lib)
}

# 1. Install Utilities
install.packages("jsonlite") # For formatting the API output
install.packages("zoo")      # For rolling calculations (medians)

# 2. Install Financial Modeling Packages
# rugarch is the heavy lifter here. It depends on Rcpp and others, 
# which will be installed automatically.
install.packages("rugarch")

# Note: 'plumber' is already installed in the base image we will use,
# but we check just in case.
if (!requireNamespace("plumber", quietly = TRUE)) install.packages("plumber")
