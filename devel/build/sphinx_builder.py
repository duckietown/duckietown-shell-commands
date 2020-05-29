import os
import os.path
import tempfile
import git
import subprocess
import docker
import copy

DOCS_BUILDER_GIT_REPOSITORY = "https://github.com/duckietown/docs-sphinx-builder.git"

class SphinxBuilder():
    def __init__(self, workspace):
        self.workspace = workspace
        self.dir_docs_source = os.path.join(self.workspace, 'docs_source')
        self.tempdir = None

    def check_if_directory_and_files_exist(self):

        def existence_test_wrapper(path):
            if not os.path.exists(path):
                raise RuntimeError(f"{path} doesn't exist and is required for building the Sphinx documentation!")

        # check if directory exists
        existence_test_wrapper(self.dir_docs_source)
        # check if the config file exists
        existence_test_wrapper(os.path.join(self.dir_docs_source, 'docs_config.yaml'))
        # check if the index.rst file exists
        existence_test_wrapper(os.path.join(self.dir_docs_source, 'index.rst'))

    def clone_docs_sphinx(self):

        # Clone docs-sphinx-builder (in a tmp folder)
        self.tempdir = tempfile.mkdtemp()
        git.Git(self.tempdir).clone(DOCS_BUILDER_GIT_REPOSITORY, depth=1)

        for i in os.listdir(self.dir_docs_source):
            cmd = 'cp -r ' + os.path.join(self.dir_docs_source, i) + f' {self.tempdir}/docs-sphinx-builder/docs/source/.'
            subprocess.Popen(cmd, shell=True)

    def build_run_container(self, base_image):

        client = docker.from_env()
        image, image_logs = client.images.build(path=f'{self.tempdir}/docs-sphinx-builder/docs',
                                                buildargs={'BASE_IMAGE_TAG': base_image})

        image_logs = ''.join([l['stream'] for l in image_logs if 'stream' in l])

        container = client.containers.run(image=image.id,
                                          command='bash -c "cp -r /docs docs; cd docs; make html; cp -r build /docs/build"',
                                          volumes={f'{self.tempdir}/docs-sphinx-builder/docs': {'bind': '/docs', 'mode': 'rw'}},
                                          detach=True)

        exit_code = container.wait()['StatusCode']
        container_logs = copy.deepcopy(container.logs()).decode("utf-8")

        # remove docker artifacts
        container.remove(v=True)
        client.images.remove(image.id)

        logs = image_logs+'\n\n'+container_logs

        if exit_code == 0:
            # successful exit
            return True, logs
        else:
            # unsuccessful exit
            return False, logs

    def copy_files_back(self):
        cmd = f'if [ -d "docs_html" ]; then rm -Rf docs_html; fi; cp -r {self.tempdir}/docs-sphinx-builder/docs/build/html docs_html'
        subprocess.Popen(cmd, shell=True)
