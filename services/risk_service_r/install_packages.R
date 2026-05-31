# services/risk_service_r/install_packages.R

# Set a reliable CRAN mirror and use all available cores for parallel C++ compile
options(repos = c(CRAN = "https://cloud.r-project.org/"),
        Ncpus = max(1L, parallel::detectCores() - 1L))

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

# Wrap install.packages so a silent failure (e.g. C++ compile error in a dep)
# fails the Docker RUN step instead of producing a runtime "no package called X".
install_or_die <- function(pkg) {
  message(sprintf(">>> Installing %s ...", pkg))
  install.packages(pkg, dependencies = TRUE)
  if (!requireNamespace(pkg, quietly = TRUE)) {
    stop(sprintf("FATAL: package %s failed to install or load", pkg))
  }
  message(sprintf(">>> %s OK (version %s)", pkg, packageVersion(pkg)))
}

# 1. Utilities
install_or_die("jsonlite")
install_or_die("zoo")

# 2. Financial modelling — heavy compile, needs build-essential + BLAS/LAPACK
install_or_die("rugarch")

# 3. plumber — usually preinstalled by the rstudio/plumber base image, but
# verify so we fail fast if the base image ever changes.
install_or_die("plumber")
