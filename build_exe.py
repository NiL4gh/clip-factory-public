import os
import sys
import subprocess

def build_exe():
    print("Starting ClipFactory AI Production EXE Build...")
    
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Ensure frontend is built
    frontend_dir = os.path.join(repo_dir, "frontend")
    if "--skip-frontend" not in sys.argv:
        print(f"Building frontend in {frontend_dir}...")
        subprocess.run(["npm", "run", "build"], cwd=frontend_dir, shell=True, check=True)
    else:
        print("Skipping frontend build (--skip-frontend).")

    # Prepare PyInstaller command
    # We bundle run_app.py which launches Uvicorn/Next.js and manages the single-instance lock.
    pyinstaller_cmd = [
        "pyinstaller",
        "--noconfirm",
        "--name", "ClipFactory",
        "--noconsole",
        "--icon", "app_icon.ico",
        "--collect-all", "webview",
        "--add-data", f"frontend/out;frontend/out",
        "--add-data", f"server;server",
        "--add-data", f"shorts_generator;shorts_generator",
        "--add-data", f"work/fonts;work/fonts",
        "--add-data", f"app_icon.ico;.",
        "--hidden-import", "uvicorn",
        "--hidden-import", "fastapi",
        "--hidden-import", "pydantic",
        "--hidden-import", "pywebview",
        "run_app.py"
    ]
    
    # We assume ffmpeg.exe and ffprobe.exe are placed in the root directory before building,
    # or they can be downloaded by the app, but since it's a bundled EXE, we should include them if they exist.
    if os.path.exists(os.path.join(repo_dir, "ffmpeg.exe")):
        pyinstaller_cmd.extend(["--add-data", "ffmpeg.exe;."])
    if os.path.exists(os.path.join(repo_dir, "ffprobe.exe")):
        pyinstaller_cmd.extend(["--add-data", "ffprobe.exe;."])
        
    print(f"Running PyInstaller...")
    subprocess.run(pyinstaller_cmd, cwd=repo_dir, shell=True, check=True)

    # PyInstaller 6 onedir puts --add-data files into _internal/, but run_app.py
    # prepends os.path.dirname(sys.executable) (the EXE's own folder) to PATH.
    # Copy ffmpeg/ffprobe NEXT TO the EXE so the bundled binaries actually win.
    dist_dir = os.path.join(repo_dir, "dist", "ClipFactory")
    for bin_name in ("ffmpeg.exe", "ffprobe.exe"):
        src = os.path.join(repo_dir, bin_name)
        if os.path.exists(src):
            import shutil
            shutil.copy2(src, os.path.join(dist_dir, bin_name))
            print(f"Bundled {bin_name} next to ClipFactory.exe")

    print("Build complete. Check the 'dist/ClipFactory' folder.")

if __name__ == "__main__":
    build_exe()
