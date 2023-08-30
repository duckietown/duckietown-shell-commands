import json
import os
import shutil
from typing import List

from dt_shell import dtslogger, UserError

__all__ = ["convert_notebooks"]


def convert_notebooks(config_files: List):
    assert isinstance(config_files, list), config_files
    for file_ in config_files:
        if "notebook" in file_:
            target_dir = file_["notebook"]["target_dir"]
            notebook_file = file_["notebook"]["input_file"]

            dtslogger.info(f"Converting the {notebook_file} into a Python script...")

            convertNotebook(notebook_file, target_dir)

        if "file" in file_:
            target_dir = file_["file"]["target_dir"]
            input_file = file_["file"]["input_file"]
            target = os.path.join(target_dir, os.path.basename(input_file))

            dtslogger.info(f"Copying {input_file} into {target_dir} ...")

            if not os.path.isfile(input_file):
                msg = f"No such file '{input_file}'. Make sure the config.yaml is correct."
                raise UserError(msg)

            shutil.copy(input_file, target)


def convertNotebook(filepath: str, target_dir: str):
    import nbformat  # install before?
    from nbconvert.exporters import PythonExporter
    from traitlets.config import Config

    if not os.path.isfile(filepath):
        msg = f"No such file '{filepath}'. Make sure the config.yaml is correct."
        raise UserError(msg)

    filename_with_extension = os.path.basename(filepath)

    with open(filepath) as f:
        data = f.read()
    j = json.loads(data)
    # dtslogger.info(str(j))
    remove_cells_without_tag(j, tag="export")
    f2 = os.path.join("/tmp", filename_with_extension)
    dtslogger.info(f"Temp filtered file : {f2}")
    with open(f2, "w") as f:
        f.write(json.dumps(j))

    nb = nbformat.read(f2, as_version=4)

    # clean the notebook, remove the cells to be skipped:
    c = Config()
    c.TagRemovePreprocessor.remove_cell_tags = ("skip",)
    # noinspection PyTypeChecker
    exporter = PythonExporter(config=c)

    # source is a tuple of python source code
    # meta contains metadata
    source, _ = exporter.from_notebook_node(nb)

    # assuming there is only one dot in the filename
    filename = filename_with_extension.split(".")[0]

    dest = os.path.join(target_dir, filename + ".py")
    try:
        with open(dest, "w") as fh:
            fh.writelines(source)
    except Exception as e:
        msg = f"Cannot write to {dest}"
        raise Exception(msg) from e

    dtslogger.info(f"Deleting temp file : {f2}")

    os.remove(f2)


def remove_cells_without_tag(j, tag: str):

    cells = j["cells"]
    cells2 = []

    for i, cell in enumerate(cells):
        cell_type = cell["cell_type"]
        if cell_type != "code":
            # msg = f"Skipping cell #{i} because not code."
            # dtslogger.info(msg)
            continue
        metadata = cell.get("metadata", {})
        tags = metadata.get("tags", [])

        if tag not in tags:
            # msg = f"Skipping cell #{i} because not tagged as {tag!r}"
            # dtslogger.info(msg)
            continue
        cells2.append(cell)

    j["cells"] = cells2
