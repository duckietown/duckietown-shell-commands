[![CircleCI](https://circleci.com/gh/duckietown/duckietown-shell-commands.svg?style=shield)](https://circleci.com/gh/duckietown/duckietown-shell-commands)

-----------------------

TODO: this should get polished and updated. 

**You need to have successfully installed the Duckietown Shell. If you know what you want to do with it go ahead. Below are some examples of things you can do with the Duckietown Shell** 

## Compile one of the "Duckumentation"

To compile one of the books (e.g. docs-duckumentation but there are many others):

    $ git clone https://github.com/duckietown/docs-duckumentation.git
    $ cd docs-duckumentation
    $ git submodule init
    $ git submodule update
    $ dts docs build

There is an incremental build system. To clean and run from scratch:

    $ dts docs clean
    $ dts docs build


### Verifying that a token is valid

To verify that a token is valid, you can use:

    $ dts tok verify dt1-TOKEN-TO-VERIFY
    
This exits with 0 if the token is valid, and writes on standard output the following json:

    {"uid": 3, "expiration": "2018-09-23"}
    
which means that the user is identified as uid 3 until the given expiration date.
 

-----------------------

## Duckiebot setup

### Command for flashing SD card

This command will install DuckieOS on the SD-card:

    $ dts init_sd_card

-----------------------

### Command for starting ROS GUIs

This command will start the ROS GUI container:

    $ dts start_gui_tools <DUCKIEBOT_NAME_GOES_HERE>

-----------------------

### Command for calibrating the Duckiebot

This command will run the Duckiebot calibration procedure:

    $ dts calibrate_duckiebot <DUCKIEBOT_NAME_GOES_HERE>

