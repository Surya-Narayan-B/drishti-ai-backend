from PyInstaller.utils.hooks import copy_metadata, collect_data_files

datas = collect_data_files('mediapipe', include_py_files=True)