# Start with the official Plumber image
FROM rstudio/plumber:latest

# ----------------------------------------------------------------
# 1. INSTALL SYSTEM DEPENDENCIES
# ----------------------------------------------------------------
# 'rugarch' requires Fortran compilers and linear algebra libraries
# (BLAS/LAPACK) to solve the GARCH equations.
RUN apt-get update -qq && apt-get install -y \
    gfortran \
    build-essential \
    libblas-dev \
    liblapack-dev \
    libglpk-dev \
    libgmp3-dev \
    libxml2-dev \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------------------------------------------
# 2. INSTALL R PACKAGES
# ----------------------------------------------------------------
# Copy the install script into the container and run it
COPY install_packages.R /install_packages.R
RUN Rscript /install_packages.R

# ----------------------------------------------------------------
# 3. SETUP APPLICATION
# ----------------------------------------------------------------
# Create a directory for the app and copy your API code
WORKDIR /app
COPY app/ /app/

# ----------------------------------------------------------------
# 4. RUNTIME CONFIGURATION
# ----------------------------------------------------------------
# Expose Port 8001 (Must match your docker-compose.yml)
EXPOSE 8001

# Start the Plumber API
# We allow connections from 0.0.0.0 (any source) so Docker networking works
CMD ["R", "-e", "pr <- plumber::plumb('/app/api.R'); pr$run(host='0.0.0.0', port=8001)"]
