import tempfile
import subprocess
import os

with tempfile.TemporaryDirectory() as tmpdirname:
    print(f'Created temporary directory {tmpdirname}')

    curr_dir_path = os.path.dirname(os.path.realpath(__file__))
    cmd = f'cp -r {curr_dir_path}/* {tmpdirname}'
    print(f'Running command {cmd}')
    subprocess.run(cmd, shell=True)

    dir_with_assets = os.path.abspath(os.path.join(curr_dir_path, '../devel/docs/build/assets/docs'))
    cmd = f'cp -r {dir_with_assets}/* {tmpdirname}'
    print(f'Running command {cmd}')
    subprocess.run(cmd, shell=True)

    cmd = f"cd {tmpdirname}; sphinx-build -b html source build/html"
    print(f'Running command {cmd}')
    subprocess.run(cmd, shell=True)
