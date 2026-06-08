"""Build the Rust native module and install it into the Python package.

Usage:
    python build_and_install.py          # Build and install
    python build_and_install.py --check  # Check if native module works
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
TARGET = ROOT / "target" / "release"
PACKAGE = ROOT / "python" / "orca_native"


def build():
    """Compile the Rust crate in release mode."""
    print("🦀 Building Rust crate...")
    result = subprocess.run(
        ["cargo", "build", "--release"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Build failed:\n{result.stderr}")
        return False
    print("   Build succeeded")
    return True


def install():
    """Copy the compiled library to the Python package."""
    import platform
    ext = ".pyd" if platform.system() == "Windows" else ".so"

    src_dll = TARGET / "orca_native.dll"
    src_so = TARGET / "orca_native.so"
    src = None
    if src_dll.exists():
        # Windows: copy .dll to .pyd (Python only recognizes .pyd/.so)
        dst = TARGET / "orca_native.pyd"
        shutil.copy2(src_dll, dst)
        print(f"   Installed: {src_dll.name} → {dst.name}")
        return True
    elif src_so.exists():
        print(f"   Found: {src_so}")
        return True
    else:
        print(f"   ERROR: No compiled library found in {TARGET}")
        return False


def check():
    """Verify the native module loads correctly."""
    sys.path.insert(0, str(PACKAGE.parent))
    try:
        from orca_native import is_native_available
        if is_native_available():
            from orca_native import search_content
            print("✅ Native module loaded and working")
            return True
        else:
            print("⚠️  Native module not available (Python fallback active)")
            return False
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build orca_native Rust extension")
    parser.add_argument("--check", action="store_true", help="Only check if native works")
    parser.add_argument("--build-only", action="store_true", help="Build without installing")
    args = parser.parse_args()

    if args.check:
        sys.exit(0 if check() else 1)

    if not build():
        sys.exit(1)

    if not args.build_only:
        if not install():
            sys.exit(1)
        check()
