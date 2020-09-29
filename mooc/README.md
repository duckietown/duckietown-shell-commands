# MOOC commands


## Test

* Usage:

    This command must be run into an exercise folder.
    
    ```dts mooc test --duckiebot_name DUCKIEBOT_NAME```

* What does it do:

    It looks for `mooc-exe.yaml`, namely a configuration file that has the following structure:

    ```yaml
    # Exercise configuration file

    exercise:
        name: exercise_name
        version: exercise_version
        packages_path: path_to_the_ros_package_in_the_image
        docker_cmd_exe: command_that_is_executed_after_running
        image_tag: docker_image_tag
        exercise_type: FUNCTION/CLASS/NODE
    ```

    Then it converts the jupyter notebook into a python script.
    After that the python script is copied into `path_to_the_ros_package_in_the_image` and the docker image is built on the Duckiebot. After building, the resulting `mooc` container is run.

## Init

* Usage:

    This command download and initialize the folder 'mooc-exercises'.

    ```dts mooc init```


* What does it do:

    It clones the repository 'mooc-exercises' and run `make start`.


## Sim //TODO

* Usage:

    This command simulate the exercise in the simulator.

    ```dts mooc sim```

* What does it do:

    //TODO

    


