#!/usr/bin/env python3
import subprocess
import sys
import os

def generate_sbom():
    print("🛡️ Generating Software Bill of Materials (SBOM) for aegis-memory...")
    
    try:
        # Check if cyclonedx-py is installed
        subprocess.run([sys.executable, "-m", "cyclonedx_py", "--help"], 
                       capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ cyclonedx-bom not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "cyclonedx-bom"], check=True)

    # Generate the SBOM in JSON format
    output_file = "sbom.json"
    print(f"📦 Outputting to {output_file}...")
    
    cmd = [
        sys.executable, "-m", "cyclonedx_py", "poetry", # works for pyproject.toml too
        "--output-format", "json",
        "--output-file", output_file
    ]
    
    # Use 'environment' to capture all installed packages in the current venv
    cmd = [
        sys.executable, "-m", "cyclonedx_py", "environment",
        "--output-format", "json",
        "--output-file", output_file
    ]

    try:
        subprocess.run(cmd, check=True)
        print(f"✅ SBOM successfully generated: {os.path.abspath(output_file)}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to generate SBOM: {e}")
        sys.exit(1)

if __name__ == "__main__":
    generate_sbom()
