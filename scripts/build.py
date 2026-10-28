"""Build the plugin zip: frontend with pnpm, Python packages with pip, then one archive for Decky.

    python scripts/build.py [--version 0.2.0] [--python 3.14] [--local]

  --version  plugin version written into the zip's package.json and the zip name (default: package.json's)
  --python   Python version of the Decky Loader that runs the plugin: compiled wheels and python3.dll must match it
  --local    also put the packages into this checkout's py_modules/ (for a checkout Decky loads directly)

Output: out/windows-quick-settings-v<version>.zip with one top folder, windows-quick-settings/. Decky keeps settings
and logs by that folder name, so it must not change between releases.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDER = "windows-quick-settings"
BUILD = os.path.join(ROOT, "build")
OUT = os.path.join(ROOT, "out")

# Files and folders of the plugin itself; py_modules/ gets the pip packages on top of these.
PLUGIN_FILES = ["main.py", "plugin.json", "package.json", "LICENSE", "README.md", "dist/index.js", "dist/index.js.map"]
PLUGIN_DIRS = ["py_modules/winqs", "py_modules/LICENSES"]

# psutil's extension uses the stable ABI, so it loads python3.dll, which Decky's frozen Python doesn't ship. It is a
# small forwarder to python3XX.dll and comes from python.org's embeddable package of the same Python version.
PYTHON3_DLL = {
    "3.14": ("3.14.8", "a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310"),
}

# Not needed at runtime: tools pip adds, test suites, type stubs, PyInstaller hooks
STRIP_DIRS = {"bin", "__pycache__", "test", "tests", "__pyinstaller"}
STRIP_SUFFIXES = (".pyc", ".pyi")


def run(cmd, **kw):
    print(">", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def pnpm():
    exe = shutil.which("pnpm")
    if exe:
        return [exe]
    corepack = shutil.which("corepack")  # Node's corepack runs the pnpm version pinned in package.json
    if corepack:
        return [corepack, "pnpm"]
    sys.exit("pnpm not found: install Node.js (version in .nvmrc) and run `corepack enable`")


def build_frontend():
    run(pnpm() + ["install", "--frozen-lockfile"])
    run(pnpm() + ["run", "build"])


def requirement_names():
    names = set()
    with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-"):  # skip the --hash continuation lines
                names.add(normalize(re.split(r"[=<>!~ ]", line, maxsplit=1)[0]))
    return names


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def install_packages(target, python):
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
         "--require-hashes", "--requirement", os.path.join(ROOT, "requirements.txt"), "--target", target,
         "--platform", "win_amd64", "--python-version", python, "--implementation", "cp", "--only-binary=:all:"])
    # every installed distribution must be pinned in requirements.txt (pip would quietly add a new dependency)
    installed = {normalize(d.split("-")[0]) for d in os.listdir(target) if d.endswith(".dist-info")}
    extra = installed - requirement_names()
    if extra:
        sys.exit("not pinned in requirements.txt: " + ", ".join(sorted(extra)))
    for d in os.listdir(target):
        if d.endswith(".dist-info"):
            shutil.rmtree(os.path.join(target, d))
    for dirpath, dirnames, filenames in os.walk(target, topdown=True):
        for d in [d for d in dirnames if d in STRIP_DIRS]:
            shutil.rmtree(os.path.join(dirpath, d))
            dirnames.remove(d)
        for f in filenames:
            if f.endswith(STRIP_SUFFIXES):
                os.remove(os.path.join(dirpath, f))


def add_python3_dll(target, python):
    if python not in PYTHON3_DLL:
        sys.exit("no python3.dll pinned for Python %s: add it to PYTHON3_DLL in %s" % (python, __file__))
    version, sha256 = PYTHON3_DLL[python]
    cache = os.path.join(BUILD, "cache", "python-%s-embed-amd64.zip" % version)
    if not os.path.exists(cache):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        url = "https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip" % (version, version)
        print("> download", url, flush=True)
        urllib.request.urlretrieve(url, cache + ".part")
        os.replace(cache + ".part", cache)
    with open(cache, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != sha256:
        os.remove(cache)
        sys.exit("python-%s-embed-amd64.zip: sha256 %s, expected %s" % (version, digest, sha256))
    with zipfile.ZipFile(cache) as z, open(os.path.join(target, "psutil", "python3.dll"), "wb") as out:
        out.write(z.read("python3.dll"))


def stage(version, python):
    dest = os.path.join(BUILD, FOLDER)
    shutil.rmtree(dest, ignore_errors=True)
    for rel in PLUGIN_FILES:
        os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), os.path.join(dest, rel))
    for rel in PLUGIN_DIRS:
        shutil.copytree(os.path.join(ROOT, rel), os.path.join(dest, rel), ignore=shutil.ignore_patterns("__pycache__"))
    with open(os.path.join(dest, "package.json"), encoding="utf-8") as f:
        package = json.load(f)
    package["version"] = version
    with open(os.path.join(dest, "package.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(package, f, indent=2, ensure_ascii=False)
        f.write("\n")
    py_modules = os.path.join(dest, "py_modules")
    install_packages(py_modules, python)
    add_python3_dll(py_modules, python)
    return dest


def make_zip(dest, version):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "%s-v%s.zip" % (FOLDER, version))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(dest):
            dirnames.sort()
            for f in sorted(filenames):
                full = os.path.join(dirpath, f)
                z.write(full, os.path.join(FOLDER, os.path.relpath(full, dest)))
    return path


def remove(path):
    """Delete a file or folder. A running Decky keeps the plugin's DLLs loaded; Windows refuses to delete those but
    lets them be renamed, so they are moved aside (*.old) and deleted by a later build."""
    paths = [path] if os.path.isfile(path) else [os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs]
    for p in paths:
        try:
            os.remove(p)
        except PermissionError:
            os.replace(p, "%s.%d.old" % (p, os.getpid()))
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def install_local(dest):
    """Replace the pip packages in this checkout's py_modules/ with the staged ones (own code is left alone).
    Restart Decky afterwards: Python modules that are already loaded keep running until then."""
    own = {os.path.basename(d) for d in PLUGIN_DIRS}
    local = os.path.join(ROOT, "py_modules")
    for name in os.listdir(local):
        if name not in own:
            remove(os.path.join(local, name))
    staged = os.path.join(dest, "py_modules")
    for name in os.listdir(staged):
        if name not in own:
            src, dst = os.path.join(staged, name), os.path.join(local, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)  # a folder kept by a renamed locked file may remain
            else:
                shutil.copy2(src, dst)


def main():
    with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as f:
        current = json.load(f)["version"]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", default=current, help="plugin version (default: %(default)s from package.json)")
    ap.add_argument("--python", default="3.14", help="Decky Loader's Python version (default: %(default)s)")
    ap.add_argument("--local", action="store_true", help="also update this checkout's py_modules/")
    args = ap.parse_args()
    version = args.version.lstrip("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit("version must look like 1.2.3, got %r" % args.version)

    build_frontend()
    dest = stage(version, args.python)
    path = make_zip(dest, version)
    if args.local:
        install_local(dest)
    print("built", os.path.relpath(path, ROOT), "(%d KB)" % (os.path.getsize(path) // 1024))


if __name__ == "__main__":
    main()
