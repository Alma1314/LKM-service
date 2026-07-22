"""Global pytest fixtures and configuration."""
import os

# Ensure tests always run with the test flag to allow weak JWT secrets
os.environ["PYTEST_RUNNING"] = "1"
